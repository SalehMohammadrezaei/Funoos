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
  the boundary, the usual outflow condition) and never comes back.
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
        self.mass_in = 0.0                  # tracer injected (the slug, plus what the inflow brings)
        self.mass_out = 0.0                 # tracer that has left through the outlet
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
        adv = self.dx / self.u_max if self.u_max > 0 else np.inf
        dif = self.dx * self.dx / (4.0 * self.dm) if self.dm > 0 else np.inf
        self.dt = float(safety * min(adv, dif))
        if not np.isfinite(self.dt) or self.dt <= 0:
            raise ValueError("tracer step is not positive: the velocity field and diffusivity are both zero")
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
        self.mass_in = float(self.c.sum())
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
        c_last = c[:, -1] if self.axis == "x" else c[-1, :]                   # last cell before the cut
        c_first = c[:, 0] if self.axis == "x" else c[0, :]
        # At the cut the water keeps flowing, but the tracer does not come round with it: what
        # leaves carries the interior concentration, what arrives carries c_in, and no diffusion
        # crosses the boundary.
        # Whichever side of the cut is upstream loses tracer; the downstream side receives the
        # arriving concentration. Most faces run outward, but a few can run backward, and those
        # must drain their cell rather than feed it.
        out_side = ub >= 0.0
        f_last = np.where(out_side, ub * c_last, ub * self.c_in)      # the face as the last cell sees it
        f_first = np.where(out_side, ub * self.c_in, ub * c_first)    # the face as the first cell sees it
        if self.axis == "x":
            fx[:, -1] = f_last
        else:
            fy[-1, :] = f_last
        div = _divergence(fx, fy, self.dx)
        if self.axis == "x":
            div[:, 0] += (f_last - f_first) / self.dx
        else:
            div[0, :] += (f_last - f_first) / self.dx
        c -= self.dt * div
        c[self.solid] = 0.0
        np.clip(c, 0.0, None, out=c)
        leaving = np.clip(f_last, 0.0, None) + np.clip(-f_first, 0.0, None)
        arriving = np.clip(f_first, 0.0, None) + np.clip(-f_last, 0.0, None)
        self.mass_out += float(self.dt * leaving.sum() / self.dx)
        self.mass_in += float(self.dt * arriving.sum() / self.dx)
        self.t += self.dt
        return self

    # ---------------------------------------------------------------- measurements
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
        """(centre of mass, variance) of the plume along the flow direction, in cells."""
        p = self.profile()
        s = float(p.sum())
        if s <= 0:
            return 0.0, 0.0
        x = np.arange(p.size, dtype=np.float64)
        mean = float((p * x).sum() / s)
        var = float((p * (x - mean) ** 2).sum() / s)
        return mean, var


def run(ux, uy, solid, dm, axis="x", injection="continuous", steps=4000, nframes=100,
        pulse_width=0.06, progress=None, safety=0.4):
    """March a tracer through the pore space and record frames and measurements.

    Returns (frames, times, record); the record holds the breakthrough curve (flux-averaged at the
    open outlet), the plume moments, and the injected/left/remaining masses at every frame.
    """
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
        if i % every == 0:
            record()
            if progress is not None:
                progress(i / steps)
    rec = {"div_u_max": tr.div_u_max, "div_u_before": tr.div_u_before,
           "breakthrough": bt, "outlet_slab_mean": slab, "centre_cells": centre,
           "variance_cells2": var, "mass": mass, "mass_out": out, "mass_in": inj,
           "balance": bal, "mass_initial": inj[0] if inj else 0.0,
           "dt": tr.dt, "u_max": tr.u_max, "dm": tr.dm,
           "numerical_diffusion": numerical_diffusion(tr.u_max, tr.dx), "pore_volume": tr.pore_volume}
    return frames, times, rec
