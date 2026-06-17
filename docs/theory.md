# FlowZoo — methods & validation notes

Each exhibit is a from-scratch implementation of a distinct numerical method.
This file records the governing equations, the discretization, and how each is
validated.

## 1. Lattice Boltzmann (D2Q9) — `solvers/lbm`
Solves incompressible flow via the discrete Boltzmann equation on a 9-velocity
lattice with a BGK collision operator:

  f_q(x + c_q, t+1) = f_q(x,t) − (1/τ)·[f_q − f_q^eq]

Macroscopic ρ, **u** are velocity moments of f_q; the kinematic viscosity is
ν = (τ − 1/2)/3. Obstacles use half-way bounce-back; the inlet is an
equilibrium velocity boundary, the outlet zero-gradient, and the transverse
boundaries periodic. A brief oscillating inlet "gust" seeds the wake
instability so the von Kármán street develops, then self-sustains.

**Exhibits:** Kármán vortex street, flow-around-your-name (text → obstacle mask).
**Validation:** shedding frequency from a wake probe → **Strouhal St = 0.20** at
Re ≈ 160 (accepted value ≈ 0.2).

## 2. Incompressible Navier–Stokes (projection) — `solvers/incompressible`
Chorin projection / "stable fluids": semi-Lagrangian advection (unconditionally
stable), a red-black Gauss–Seidel SOR pressure Poisson solve enforcing
∇·**u** = 0, Boussinesq buoyancy from an advected scalar, and vorticity
confinement to restore small-scale swirl lost to numerical diffusion.

**Exhibits:** rising smoke plume (buoyant source), Rayleigh–Taylor instability
(heavy-over-light under gravity).

## 3. Compressible Euler (finite volume) — `solvers/compressible`
Conservative variables [ρ, ρu, ρv, E], piecewise-linear MUSCL reconstruction
with a minmod limiter, an **HLLC** approximate Riemann solver at the faces, and
SSP-RK2 time stepping with a CFL-limited dt. Transmissive (zero-gradient)
boundaries. γ = 1.4.

**Exhibits:** Sod shock tube (validation), explosion / blast wave,
shock–bubble interaction (schlieren).
**Validation:** density vs. the **exact Sod Riemann solution** — mean absolute
error ≈ 0.002; rarefaction, contact, and shock all captured.

## 4. Smoothed-Particle Hydrodynamics — `solvers/sph`
Weakly-compressible SPH: cubic-spline kernel, density by continuity, a Tait
equation of state p = B[(ρ/ρ₀)^γ − 1] (pressure clamped ≥ 0 to suppress the
free-surface tensile instability), Monaghan artificial viscosity, and a uniform
grid for neighbor search. Walls use a bounded repulsive force plus a reflective
clamp; a velocity limiter guards stability.

**Exhibit:** dam break splash.
**Validation:** the surge-front advances at ≈ 0.7× the frictionless Ritter
dry-bed limit 2√(gH) — within the physical range, since a real column must
first collapse vertically and lags the shallow-water bound.

## 5. Pseudo-spectral (FFT) — `flowzoo/spectral.py`
2D vorticity–streamfunction form in a periodic box. The streamfunction comes
from ∇²ψ = −ω (a division by k² in Fourier space); the nonlinear advection term
is formed in physical space with 2/3-rule dealiasing; viscosity is exact in
spectral space; time stepping is RK4 (stable for the advection operator's
imaginary eigenvalues).

**Exhibit:** Kelvin–Helmholtz billows → 2D turbulence.
**Validation:** with ν = 0 the scheme conserves kinetic energy to **≈ 1.5×10⁻⁷**
over hundreds of steps — the spectral-accuracy signature.
