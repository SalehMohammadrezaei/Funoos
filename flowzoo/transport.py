"""Advection and dispersion of a tracer through a pore space (the ADE).

    ∂c/∂t + ∇·(u c) = ∇·(D_m ∇c)

on the same grid as the porous-flow solver, with the grains impermeable. Only molecular
diffusion D_m is put in: the spreading that a plume actually shows (mechanical dispersion)
comes out of the pore-scale velocity field itself, because neighbouring channels carry the
tracer at different speeds. Nothing about dispersion is assumed.

The velocity field
------------------
The flow solver reports velocities at cell centres. Averaging those onto the faces of this grid
and closing the faces that touch a grain gives a field that is *almost* divergence-free, but not
exactly: what flows into a pore cell and what flows out differ by a little. A transport scheme
cannot tell that error from a real source of tracer, and on a grid cut by grains the error is
large enough to matter. So the face field is **projected** first: a potential is solved on the
pore space and subtracted, leaving ∇·u = 0 to the solver tolerance (`div_u_max` reports what is
left, `div_u_before` what it was). Only then is the tracer advanced, with the conservative
scheme, so tracer is neither created nor destroyed in the interior and a concentration entering
at 1 can never exceed 1.

Boundaries
----------
The flow is periodic, and the tracer keeps that periodicity **across** the flow. Along the flow
the water still crosses the periodic face, but the tracer does not follow it round: that face is
the sample's inlet and outlet.

* **Outlet**: open. Tracer leaves with the water (advective flux only; no diffusive flux through
  the boundary, the usual outflow condition) and never comes back. A few outlet faces can run
  backwards; the water they draw in comes from the sample's own effluent region, which is clean
  (`c_out`, zero here). Feeding those faces the injected concentration would put tracer into the
  downstream end of the sample ahead of the front, which is not an outlet at all.
* **Inlet**: the arriving water carries a prescribed concentration: zero for a pulse, so nothing
  re-enters once the slug has gone, or the injected value for a steady supply.

Without that cut a periodic sample has no outlet at all: tracer leaving downstream re-enters
upstream, a breakthrough curve picks up its own recycled tracer, and a steady supply simply fills
the box.

Everything entering and leaving is counted, so the tracer is accounted for exactly:

    tracer inside  =  tracer injected  −  tracer that has left

which closes to round-off. The breakthrough curve is the **flux-averaged** concentration at the
outlet, Σ u c / Σ u over the outlet face: the concentration of the water actually leaving, which
is what a sampler at the end of a column measures. A plain pore average over an outlet slab is
available too, but it is not what a breakthrough curve means.

Numerics
--------
Finite volume on the cell-centred grid: fluxes live on faces, so what leaves one cell enters the
next, and faces touching a grain carry nothing (∂c/∂n = 0 on every grain surface). Advection is
first-order upwind, diffusion is the five-point Laplacian, and the step is explicit with

    dt = safety · min( dx / max|u| ,  dx² / (4 D_m) )

so both the Courant and the diffusive limits hold. First-order upwind adds numerical diffusion of
order u·dx/2, reported next to the measured spreading rather than hidden.

The flow is taken as steady. In these samples the pore Reynolds number is far below one, so the
field the flow solver settles to does not change while the tracer crosses: freezing it is exact
here, not an approximation for convenience.
"""
import numpy as np

__all__ = ["Transport", "numerical_diffusion", "project"]


# Below this, a negative concentration is round-off in a monotone update; above it, something is
# actually wrong. Concentrations here are order 1 (the injected value), so this is an absolute bound.
_NEGATIVE_TOLERANCE = 1e-10


def numerical_diffusion(u_max, dx):
    """Numerical diffusivity of first-order upwind advection, ~ |u| dx / 2 (same units as D_m)."""
    return 0.5 * float(u_max) * float(dx)


def _divergence(fx, fy, dx):
    """Net outflow per unit volume of a face field (periodic rolls)."""
    return (fx - np.roll(fx, 1, axis=1)) / dx + (fy - np.roll(fy, 1, axis=0)) / dx


def project(uf_x, uf_y, open_x, open_y, fluid, dx=1.0, iters=6000, tol=1e-26):
    """Remove the discrete divergence of a face-velocity field (periodic, no flux into grains).

    Solves ∇·∇φ = ∇·u on the pore space, with φ in pore cells and gradients taken only across
    open faces, then returns u − ∇φ. Conjugate gradients; the operator is singular (adding a
    constant to φ changes nothing), so the mean is removed as it goes.

    `tol` is on the squared residual, so 1e-26 asks for about thirteen digits. It is set tight on
    purpose: whatever divergence is left acts on the tracer as dc/dt = −c ∇·u, which a conservative
    scheme cannot tell from a real source, and it compounds over thousands of steps. At the earlier
    1e-16 a steady supply crept to 1 + 2e-7 over one sample length; at 1e-26 it holds 1 to twelve
    digits, and the extra iterations cost hundredths of a second.

    Returns (uf_x, uf_y, residual_max).
    """
    f = fluid.astype(np.float64)
    rhs = _divergence(uf_x, uf_y, dx) * f

    def apply(phi):
        gx = np.where(open_x, (np.roll(phi, -1, axis=1) - phi) / dx, 0.0)
        gy = np.where(open_y, (np.roll(phi, -1, axis=0) - phi) / dx, 0.0)
        return _divergence(gx, gy, dx) * f

    phi = np.zeros_like(rhs)
    r = (rhs - apply(phi)) * f
    r -= r[fluid].mean() * f
    p = r.copy()
    rs = float((r * r).sum())
    rs0 = rs
    for _ in range(iters):
        if rs <= tol * max(rs0, 1e-300):
            break
        ap = apply(p)
        denom = float((p * ap).sum())
        if abs(denom) < 1e-300:
            break
        alpha = rs / denom
        phi += alpha * p
        r -= alpha * ap
        r *= f
        r -= r[fluid].mean() * f
        rs_new = float((r * r).sum())
        p = r + (rs_new / rs) * p
        rs = rs_new
    gx = np.where(open_x, (np.roll(phi, -1, axis=1) - phi) / dx, 0.0)
    gy = np.where(open_y, (np.roll(phi, -1, axis=0) - phi) / dx, 0.0)
    ux_new, uy_new = uf_x - gx, uf_y - gy
    resid = float(np.abs(_divergence(ux_new, uy_new, dx)[fluid]).max(initial=0.0))
    return ux_new, uy_new, resid


class Transport:
    """Tracer transport on a fixed velocity field inside a pore space.

    ux, uy : velocity components at cell centres (lattice units, [y, x])
    solid  : boolean grain mask, True where fluid cannot go
    dm     : molecular diffusivity (lattice units)
    axis   : "x" or "y", the direction the flow is driven along (inlet, outlet and profiles)
    """

    def __init__(self, ux, uy, solid, dm, axis="x", dx=1.0, safety=0.4, project_field=True):
        self.ux = np.ascontiguousarray(ux, dtype=np.float64)
        self.uy = np.ascontiguousarray(uy, dtype=np.float64)
        self.solid = np.ascontiguousarray(solid, dtype=bool)
        self.fluid = ~self.solid
        self.dm = float(dm)
        self.axis = "y" if str(axis).lower().startswith("y") else "x"
        self.dx = float(dx)
        self.ny, self.nx = self.solid.shape
        self.c = np.zeros((self.ny, self.nx), dtype=np.float64)
        self.t = 0.0
        self.c_in = 0.0                     # concentration of the water arriving at the inlet
        self.c_out = 0.0                    # concentration outside the outlet (the effluent region)
        self.mass_initial = 0.0             # tracer placed in the sample at t = 0 (a slug)
        # Every crossing is counted at the end it crosses and in the direction it goes, so a
        # breakthrough and a loss back out of the inlet are never added into the same number.
        self.inlet_in = 0.0                 # arrived through the inlet
        self.inlet_out = 0.0                # left backwards through the inlet
        self.outlet_out = 0.0               # left through the outlet (the breakthrough)
        self.outlet_in = 0.0                # drawn back in through a reversed outlet face
        # a face is open where both neighbouring cells are pore space
        self.open_x = self.fluid & np.roll(self.fluid, -1, axis=1)      # face between (i) and (i+1) in x
        self.open_y = self.fluid & np.roll(self.fluid, -1, axis=0)
        # face velocities (average of the two cells, zero on a closed face), made divergence-free
        self.uf_x = np.where(self.open_x, 0.5 * (self.ux + np.roll(self.ux, -1, axis=1)), 0.0)
        self.uf_y = np.where(self.open_y, 0.5 * (self.uy + np.roll(self.uy, -1, axis=0)), 0.0)
        self.div_u_before = float(np.abs(_divergence(self.uf_x, self.uf_y, self.dx)[self.fluid]).max(initial=0.0))
        if project_field:
            self.uf_x, self.uf_y, self.div_u_max = project(self.uf_x, self.uf_y, self.open_x,
                                                           self.open_y, self.fluid, self.dx)
        else:
            self.div_u_max = self.div_u_before
        self.u_max = float(max(np.abs(self.uf_x).max(initial=0.0), np.abs(self.uf_y).max(initial=0.0)))
        # The step has to keep the update monotone, and that is one condition on the whole update,
        # not two conditions met separately: a cell can satisfy the Courant limit and the diffusive
        # limit on their own and still be emptied past zero by advection and diffusion acting
        # together. So the limit is assembled per cell, from everything that drains it.
        #
        #   lambda = (advection out through each face)/dx  +  D_m (open faces)/dx^2
        #   dt     = safety / max(lambda)
        #
        # Advection only drains a cell through a face whose velocity points out of it, and upwind
        # takes that at the cell's own concentration, so the outgoing part is what counts.
        ux_r, uy_u = self.uf_x, self.uf_y                       # the cell's right and upper face
        ux_l = np.roll(self.uf_x, 1, axis=1)                    # its left face is the previous one
        uy_d = np.roll(self.uf_y, 1, axis=0)
        out_rate = (np.maximum(ux_r, 0.0) + np.maximum(-ux_l, 0.0)
                    + np.maximum(uy_u, 0.0) + np.maximum(-uy_d, 0.0)) / self.dx
        # Diffusion crosses open faces only, and never the cut: step() overwrites that face with
        # the boundary flux, so it carries no diffusive term and must not be counted here.
        dif_x, dif_y = self.open_x.copy(), self.open_y.copy()
        if self.axis == "x":
            dif_x[:, -1] = False
        else:
            dif_y[-1, :] = False
        faces = (dif_x.astype(np.float64) + np.roll(dif_x, 1, axis=1)
                 + dif_y.astype(np.float64) + np.roll(dif_y, 1, axis=0))
        lam = out_rate + self.dm * faces / (self.dx * self.dx)
        lam_max = float(lam[self.fluid].max(initial=0.0))
        self.dt = float(safety / lam_max) if lam_max > 0 else float("inf")
        if not np.isfinite(self.dt) or self.dt <= 0:
            raise ValueError("tracer step is not positive: the velocity field and diffusivity are both zero")
        self.clipped_mass = 0.0      # tracer removed by round-off clipping, reported, never hidden
        # the face where the tracer's domain is cut: the sample's inlet and outlet
        self.uf_boundary = (self.uf_x[:, -1] if self.axis == "x" else self.uf_y[-1, :]).copy()
        self.pore_volume = float(self.fluid.sum())

    # ---------------------------------------------------------------- what is injected
    def pulse(self, width=0.06, amplitude=1.0):
        """A slug of tracer across the inlet end; afterwards the inflow is clean water."""
        n = self.nx if self.axis == "x" else self.ny
        w = max(1, int(round(width * n)))
        self.c[:] = 0.0
        if self.axis == "x":
            self.c[:, :w] = amplitude
        else:
            self.c[:w, :] = amplitude
        self.c[self.solid] = 0.0
        self.c_in = 0.0
        self.mass_initial = float(self.c.sum())
        return self

    def set_inlet(self, value=1.0):
        """A steady supply: the water arriving at the inlet carries this concentration."""
        self.c_in = float(value)
        return self

    # ---------------------------------------------------------------- one step
    def step(self):
        c = self.c
        cxp = np.roll(c, -1, axis=1)
        cyp = np.roll(c, -1, axis=0)
        fx = np.where(self.uf_x >= 0.0, self.uf_x * c, self.uf_x * cxp)      # upwind advection
        fy = np.where(self.uf_y >= 0.0, self.uf_y * c, self.uf_y * cyp)
        if self.dm > 0.0:                                                     # diffusion
            fx -= np.where(self.open_x, self.dm * (cxp - c) / self.dx, 0.0)
            fy -= np.where(self.open_y, self.dm * (cyp - c) / self.dx, 0.0)
        ub = self.uf_boundary
        c_last = c[:, -1] if self.axis == "x" else c[-1, :]                   # last cell, at the outlet
        c_first = c[:, 0] if self.axis == "x" else c[0, :]                    # first cell, at the inlet
        # The cut is two separate boundaries that happen to share one face velocity: the outlet at
        # the downstream edge of the sample and the inlet at the upstream edge. What crosses each
        # depends on which way that face runs, and the four cases carry different concentrations:
        #
        #   outlet, ub >= 0 : water leaves, carrying the interior concentration
        #   outlet, ub <  0 : water is drawn in from the effluent region, which is clean (c_out)
        #   inlet,  ub >= 0 : water arrives, carrying the feed (c_in)
        #   inlet,  ub <  0 : water leaves backwards, carrying the interior concentration
        #
        # The outlet's reversed case is the one that matters: handing it c_in would inject tracer
        # into the downstream end of the sample before anything had travelled there.
        out_side = ub >= 0.0
        f_out = np.where(out_side, ub * c_last, ub * self.c_out)      # flux through the outlet face
        f_in = np.where(out_side, ub * self.c_in, ub * c_first)       # flux through the inlet face
        if self.axis == "x":
            fx[:, -1] = f_out
        else:
            fy[-1, :] = f_out
        div = _divergence(fx, fy, self.dx)
        if self.axis == "x":
            div[:, 0] += (f_out - f_in) / self.dx
        else:
            div[0, :] += (f_out - f_in) / self.dx
        c -= self.dt * div
        c[self.solid] = 0.0
        # With the step above the update is monotone, so a negative concentration here is either
        # round-off or a real defect. Round-off is clipped and its mass recorded; anything larger
        # is raised, because clipping it away would turn a broken calculation into a plausible
        # picture and silently create tracer (the clip adds back exactly what it removes).
        low = float(c.min())
        if low < 0.0:
            if low < -_NEGATIVE_TOLERANCE:
                raise ValueError(
                    f"tracer concentration went to {low:.3e}: the transport step is not monotone "
                    f"(dt={self.dt:.6g}); this is a solver defect, not a setting to adjust")
            self.clipped_mass += float(-c[c < 0.0].sum())
            np.clip(c, 0.0, None, out=c)
        d = self.dt / self.dx                                          # positive flux runs downstream
        self.outlet_out += float(d * np.clip(f_out, 0.0, None).sum())
        self.outlet_in += float(d * np.clip(-f_out, 0.0, None).sum())
        self.inlet_in += float(d * np.clip(f_in, 0.0, None).sum())
        self.inlet_out += float(d * np.clip(-f_in, 0.0, None).sum())
        self.t += self.dt
        return self

    # ---------------------------------------------------------------- measurements
    @property
    def mass_in(self):
        """Everything that has entered: the slug placed at t = 0, plus what has crossed inwards at
        either end. With a clean effluent region `outlet_in` is zero, and it is kept separate so
        that a sample which does draw water back in cannot hide it inside the inlet total."""
        return self.mass_initial + self.inlet_in + self.outlet_in

    @property
    def mass_out(self):
        """Everything that has left, through the outlet (the breakthrough) or backwards out of the
        inlet. `outlet_out` alone is the breakthrough."""
        return self.outlet_out + self.inlet_out

    def mass(self):
        return float(self.c.sum())

    def balance(self):
        """Injected − left − what is still inside; zero to round-off if the bookkeeping is right."""
        return float(self.mass_in - self.mass_out - self.mass())

    def outlet_concentration(self):
        """Flux-averaged concentration of the water leaving: Σ u c / Σ u over the outlet face.
        This is what a sampler at the end of a column measures, and what a breakthrough curve means."""
        c_last = self.c[:, -1] if self.axis == "x" else self.c[-1, :]
        pos = self.uf_boundary > 0
        tot = float(self.uf_boundary[pos].sum())
        return float((self.uf_boundary[pos] * c_last[pos]).sum() / tot) if tot > 0 else 0.0

    def outlet_mean(self, width=0.05):
        """Plain pore average over a slab at the outlet end (not a breakthrough curve)."""
        n = self.nx if self.axis == "x" else self.ny
        w = max(1, int(round(width * n)))
        sl, fl = ((self.c[:, -w:], self.fluid[:, -w:]) if self.axis == "x"
                  else (self.c[-w:, :], self.fluid[-w:, :]))
        k = int(fl.sum())
        return float(sl[fl].sum() / k) if k else 0.0

    def profile(self):
        """Pore-averaged concentration along the flow direction (one value per column/row)."""
        fl = self.fluid.astype(np.float64)
        if self.axis == "x":
            num, den = (self.c * fl).sum(axis=0), fl.sum(axis=0)
        else:
            num, den = (self.c * fl).sum(axis=1), fl.sum(axis=1)
        return np.divide(num, den, out=np.zeros_like(num), where=den > 0)

    def moments(self):
        """(centre of mass, variance) of the plume along the flow direction, in cells.

        Weighted by the tracer each slice actually holds, not by its pore-averaged concentration.
        The two differ wherever the pore space does: a slice with one pore cell and a slice with
        twenty hold very different amounts at the same concentration, and averaging first would
        give them equal say in where the plume is and how wide it has become.
        """
        fl = self.fluid.astype(np.float64)
        m = (self.c * fl).sum(axis=0) if self.axis == "x" else (self.c * fl).sum(axis=1)
        s = float(m.sum())
        if s <= 0:
            return 0.0, 0.0
        x = np.arange(m.size, dtype=np.float64)
        mean = float((m * x).sum() / s)
        var = float((m * (x - mean) ** 2).sum() / s)
        return mean, var


def run(ux, uy, solid, dm, axis="x", injection="continuous", steps=4000, nframes=100,
        pulse_width=0.06, progress=None, safety=0.4):
    """March a tracer through the pore space and record frames and measurements.

    Returns (frames, times, record); the record holds the breakthrough curve (flux-averaged at the
    open outlet), the plume moments, and the injected/left/remaining masses at every frame.
    """
    if injection not in ("continuous", "pulse"):
        # Anything else used to fall through to a pulse, so a caller asking for "steady" quietly
        # got the opposite experiment and a plausible-looking result.
        raise ValueError(f"injection must be 'continuous' or 'pulse', not {injection!r}")
    tr = Transport(ux, uy, solid, dm, axis=axis, safety=safety)
    if injection == "continuous":
        tr.set_inlet(1.0)
    else:
        tr.pulse(pulse_width)
    every = max(1, steps // max(1, nframes))
    frames, times = [], []
    bt, slab, centre, var, mass, out, inj, bal = [], [], [], [], [], [], [], []

    def record():
        frames.append(tr.c.copy()); times.append(tr.t)
        bt.append(tr.outlet_concentration()); slab.append(tr.outlet_mean())
        m, v = tr.moments(); centre.append(m); var.append(v)
        mass.append(tr.mass()); out.append(tr.mass_out); inj.append(tr.mass_in)
        bal.append(tr.balance())

    record()
    for i in range(1, steps + 1):
        tr.step()
        # The frame interval rarely divides the step count, and when it does not the last frame
        # recorded was the last interval rather than the end of the run: 235 steps with 110 frames
        # stopped at step 234. The breakthrough curve and the mass balance are read from the state
        # the run actually finished in, so that state is always recorded.
        if i % every == 0 or i == steps:
            record()
            if progress is not None:
                progress(i / steps)
    rec = {"div_u_max": tr.div_u_max, "div_u_before": tr.div_u_before,
           "breakthrough": bt, "outlet_slab_mean": slab, "centre_cells": centre,
           "variance_cells2": var, "mass": mass, "mass_out": out, "mass_in": inj,
           "balance": bal, "mass_initial": inj[0] if inj else 0.0,
           "dt": tr.dt, "u_max": tr.u_max, "dm": tr.dm, "injection": injection,
           # what round-off clipping removed, reported rather than absorbed silently
           "clipped_mass": tr.clipped_mass,
           "numerical_diffusion": numerical_diffusion(tr.u_max, tr.dx), "pore_volume": tr.pore_volume}
    return frames, times, rec
