"""Advection and dispersion of a tracer through a pore space (the ADE).

    ∂c/∂t + ∇·(u c) = ∇·(D_m ∇c)

on the same grid as the porous-flow solver, with the grains impermeable. Only molecular
diffusion D_m is put in: the spreading that a plume actually shows (mechanical dispersion)
comes out of the pore-scale velocity field itself, because neighbouring channels carry the
tracer at different speeds. Nothing about dispersion is assumed.

Numerics
--------
Finite volume on the cell-centred grid. Fluxes are evaluated on cell faces, so what leaves one
cell enters the next and the tracer mass is conserved to round-off; faces touching a grain carry
no flux at all (∂c/∂n = 0 on every grain surface). Advection is first-order upwind, diffusion is
the standard five-point Laplacian, and the step is explicit with

    dt = safety · min( dx / max|u| ,  dx² / (4 D_m) )

so both the Courant and the diffusive limits hold. First-order upwind adds numerical diffusion of
order u·dx/2, which is reported next to the measured spreading rather than hidden: at the default
grid it is small compared with the mechanical dispersion it is measuring, and `numerical_diffusion`
returns it so a scene can state it.

The flow is taken as steady. In these samples the pore Reynolds number is far below one, so the
velocity field the LBM settles to does not change while the tracer crosses: freezing it is exact
here, not an approximation for convenience.
"""
import numpy as np

__all__ = ["Transport", "numerical_diffusion"]


def numerical_diffusion(u_max, dx):
    """Numerical diffusivity of first-order upwind advection, ~ |u| dx / 2 (same units as D_m)."""
    return 0.5 * float(u_max) * float(dx)


class Transport:
    """Tracer transport on a fixed velocity field inside a pore space.

    ux, uy : velocity components on the grid (lattice units, [y, x])
    solid  : boolean grain mask, True where fluid cannot go
    dm     : molecular diffusivity (lattice units)
    axis   : "x" or "y", the direction the flow is driven along (sets inlet, outlet and profiles)
    """

    def __init__(self, ux, uy, solid, dm, axis="x", dx=1.0, safety=0.4):
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
        self.u_max = float(max(np.abs(self.ux[self.fluid]).max(initial=0.0),
                               np.abs(self.uy[self.fluid]).max(initial=0.0)))
        adv = self.dx / self.u_max if self.u_max > 0 else np.inf
        dif = self.dx * self.dx / (4.0 * self.dm) if self.dm > 0 else np.inf
        self.dt = float(safety * min(adv, dif))
        if not np.isfinite(self.dt) or self.dt <= 0:
            raise ValueError("tracer step is not positive: the velocity field and diffusivity are both zero")
        # face open where both neighbouring cells are fluid (periodic, like the flow solver)
        self.open_x = self.fluid & np.roll(self.fluid, -1, axis=1)      # face between (i) and (i+1) in x
        self.open_y = self.fluid & np.roll(self.fluid, -1, axis=0)
        # face velocities (average of the two cells, zero on a closed face)
        self.uf_x = np.where(self.open_x, 0.5 * (self.ux + np.roll(self.ux, -1, axis=1)), 0.0)
        self.uf_y = np.where(self.open_y, 0.5 * (self.uy + np.roll(self.uy, -1, axis=0)), 0.0)
        self.pore_volume = float(self.fluid.sum())

    # ---------------------------------------------------------------- initial states
    def pulse(self, width=0.06, amplitude=1.0):
        """A slab of tracer across the whole inlet end: the cleanest breakthrough curve."""
        n = self.nx if self.axis == "x" else self.ny
        w = max(1, int(round(width * n)))
        self.c[:] = 0.0
        if self.axis == "x":
            self.c[:, :w] = amplitude
        else:
            self.c[:w, :] = amplitude
        self.c[self.solid] = 0.0
        return self

    def set_inlet(self, value=1.0, width=0.02):
        """Hold a fixed concentration at the inlet end: a steady supply (a front, not a pulse)."""
        n = self.nx if self.axis == "x" else self.ny
        w = max(1, int(round(width * n)))
        self._inlet = (value, w)
        self._apply_inlet()
        return self

    def _apply_inlet(self):
        v = getattr(self, "_inlet", None)
        if v is None:
            return
        value, w = v
        if self.axis == "x":
            self.c[:, :w] = value
        else:
            self.c[:w, :] = value
        self.c[self.solid] = 0.0

    # ---------------------------------------------------------------- one step
    def step(self):
        c = self.c
        # --- advective face fluxes, first-order upwind
        cxp = np.roll(c, -1, axis=1)
        fx = np.where(self.uf_x >= 0.0, self.uf_x * c, self.uf_x * cxp)
        cyp = np.roll(c, -1, axis=0)
        fy = np.where(self.uf_y >= 0.0, self.uf_y * c, self.uf_y * cyp)
        # --- diffusive face fluxes (closed faces carry nothing: no-flux on grain surfaces)
        if self.dm > 0.0:
            fx -= np.where(self.open_x, self.dm * (cxp - c) / self.dx, 0.0)
            fy -= np.where(self.open_y, self.dm * (cyp - c) / self.dx, 0.0)
        # --- divergence: what leaves through the right/top face enters the next cell
        div = (fx - np.roll(fx, 1, axis=1)) / self.dx + (fy - np.roll(fy, 1, axis=0)) / self.dx
        c -= self.dt * div
        c[self.solid] = 0.0
        np.clip(c, 0.0, None, out=c)
        self._apply_inlet()
        self.t += self.dt
        return self

    # ---------------------------------------------------------------- measurements
    def mass(self):
        return float(self.c.sum())

    def outlet_concentration(self, width=0.05):
        """Mean pore concentration in a slab at the outlet end: one point of the breakthrough curve."""
        n = self.nx if self.axis == "x" else self.ny
        w = max(1, int(round(width * n)))
        if self.axis == "x":
            sl, fl = self.c[:, -w:], self.fluid[:, -w:]
        else:
            sl, fl = self.c[-w:, :], self.fluid[-w:, :]
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


def run(ux, uy, solid, dm, axis="x", injection="pulse", steps=4000, nframes=100,
        pulse_width=0.06, progress=None, safety=0.4):
    """March a tracer through the pore space and record frames and measurements.

    Returns (frames, times, record) where record holds the breakthrough curve, the plume
    moments and the mass history, all sampled at the recorded frames.
    """
    tr = Transport(ux, uy, solid, dm, axis=axis, safety=safety)
    if injection == "continuous":
        tr.set_inlet(1.0)
    else:
        tr.pulse(pulse_width)
    mass0 = tr.mass()
    every = max(1, steps // max(1, nframes))
    frames, times, bt, centre, var, mass = [], [], [], [], [], []

    def record():
        frames.append(tr.c.copy()); times.append(tr.t)
        bt.append(tr.outlet_concentration())
        m, v = tr.moments(); centre.append(m); var.append(v)
        mass.append(tr.mass())

    record()
    for i in range(1, steps + 1):
        tr.step()
        if i % every == 0:
            record()
            if progress is not None:
                progress(i / steps)
    rec = {"breakthrough": bt, "centre_cells": centre, "variance_cells2": var, "mass": mass,
           "mass_initial": mass0, "dt": tr.dt, "u_max": tr.u_max, "dm": tr.dm,
           "numerical_diffusion": numerical_diffusion(tr.u_max, tr.dx), "pore_volume": tr.pore_volume}
    return frames, times, rec
