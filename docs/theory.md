# Funoos — models, numerical methods and checks

Every scene in Funoos is built on one of five from-scratch solvers. This file
states, per solver, what is solved, what is prescribed, what is a visual effect,
and what has been checked quantitatively. The per-scene pages in the app carry
the same information in layers ("What you are seeing" → "Checks and limitations").

Status labels used throughout (also shown on every scene card):

| label | meaning |
|---|---|
| **Analytical comparison** | compared with an exact solution, with the error reported |
| **Numerical check** | self-consistency, convergence or a documented reference value |
| **Qualitative demonstration** | shows the phenomenon; no quantitative claim |

## Units and time

* **Lattice Boltzmann** works in lattice units: cell size = 1, time step = 1, speed
  of sound c_s = 1/√3. ν = (τ − ½)/3. Frame times are lattice steps.
* **Incompressible solver** uses grid units with dx = dt = 1; viscosity, buoyancy
  and diffusivity are in those units. Frame times are solver steps.
* **Compressible solver** uses code units with ambient ρ = 1, p = 1 (sound speed √γ)
  for the shock scenes and p = 0.1 ambient for the blast; the Sod tube has length 1.
  Time steps are adaptive (CFL 0.4); the actual time of every saved frame is stored.
* **SPH** is dimensional: metres, seconds, ρ₀ = 1000 kg/m³, 2-D (quantities per metre
  of depth).
* **Spectral solvers** use a nondimensional 2π-periodic box; dt = 0.4·L/n.

The simulated interval of a scene is fixed by its duration setting; changing the
resolution changes only the grid (tests: `spectral fixed end time`). Frame 0 is the
initial state and the last frame the final state for every solver.

## 1. Lattice Boltzmann (D2Q9, BGK) — `solvers/lbm`

Solves weakly compressible flow via the discrete Boltzmann equation on nine
lattice velocities: f_q(x + c_q, t + 1) = f_q(x, t) − (1/τ)[f_q − f_q^eq] with a
Guo forcing term when a body force is applied (Guo, Zheng & Shi 2002). Obstacles
are solid cells with half-way bounce-back (no-slip); collisions are applied to
fluid cells only. Macroscopic velocity uses the half-force correction
u = (Σ c_q f_q + F/2)/ρ in collision, output, probes and diagnostics alike.

*Wind tunnel*: velocity inlet, zero-gradient outlet with a relaxation sponge over
the last 12 % (it weakens, but does not remove, reflections), periodic top/bottom.
The initial state is uniform flow at the inflow speed with a brief transverse
perturbation that seeds the wake instability. Setting the Reynolds number holds U
and D and recomputes ν.

*Porous flow*: periodic box, body force along x or y, fluid initially at rest.
Permeability k = ν U_D / g with U_D the **superficial** velocity (flow averaged
over the whole sample, solids counting as zero) and g the force per unit mass; the
pore-average velocity U_D/φ is stored separately.

**Checks.** Plane-Poiseuille permeability k = h³/(12 H) reproduced to 0.07 %
(second-order convergence); a slab sample gives k_x ≫ k_y and k is independent of
the driving force (Darcy linearity); a blocked sample gives k ≈ 0; the wind-tunnel
Strouhal number is compared with the 0.18–0.21 reference range for a circular
cylinder (Williamson 1996) — this confined, periodic tunnel is expected to sit
slightly above an unconfined body. Drag from the wake momentum deficit is an
approximation and labelled as such; lift comes from the circulation on a contour
around the body and changes sign with the angle (mirror test).

## 2. Incompressible Navier–Stokes (projection) — `solvers/incompressible`

Chorin projection ("stable fluids", Stam 1999): semi-Lagrangian advection of both
velocity components with the same frozen velocity field, explicit viscous
diffusion scaled by dt, a red-black SOR pressure Poisson solve enforcing ∇·u = 0,
Boussinesq buoyancy from an advected scalar, and optional vorticity confinement
(Fedkiw et al. 2001) — a modelling term added for visual detail, exposed as a
control and defaulting to 0 where a measurement matters.

* *Smoke / chimney*: buoyancy proportional to the transported scalar (a
  temperature/dye proxy); a prescribed source at the floor; the chimney scene adds
  a velocity inlet (the crosswind) and a zero-gradient outflow.
* *Rayleigh–Taylor*: density is an advected scalar that enters only the buoyancy
  term of a constant-density projection (a Boussinesq-like approximation);
  quantitative growth rates at large Atwood number are not claimed. A single-mode
  perturbation is available for measuring early growth consistently.
* *Rayleigh–Bénard*: transported temperature with explicit thermal diffusion κ
  (dt·κ ≤ 0.25), Dirichlet plates, insulating side walls. The Rayleigh number is
  computed from the controls as Ra = β·ΔT·H³/(ν κ) and shown; the buoyancy control
  is a coefficient, not Ra. With buoyancy off the conduction profile is preserved
  and the Nusselt number is 1 (tests).
* *Candle flame*: a **simplified flame model** — an advected mixture variable Z with
  a prescribed inflow velocity at the wick, lateral damping, a decay of Z away from
  the source, a temperature proxy T(Z) peaking at Z = Z_st, and buoyancy
  proportional to T. No chemistry or heat release is computed.

**Checks.** Divergence-free to the solver tolerance; RB conduction baseline and
diffusion test; RT mixing width consistent across resolutions; Nusselt number from
the conductive + convective flux budget.

## 3. Compressible Euler (finite volume, HLLC) — `solvers/compressible`

Conservative variables [ρ, ρu, ρv, E], MUSCL reconstruction with a minmod limiter,
HLLC Riemann solver at faces (Toro 2009), SSP-RK2, CFL-limited adaptive dt, γ = 1.4.
Face fluxes are computed into arrays and accumulated per cell (no atomics; results
bit-identical to the previous implementation). Domain edges are zero-gradient
(weakly reflecting, not perfectly non-reflecting).

* *Sod shock tube*: exposed as a scene; density and velocity are compared with the
  exact Riemann solution (mean |Δρ| ≈ 0.003 at 300 cells, ≈ 0.0026 at 360).
* *Blast wave*: a pressure-release model (a disc of high-pressure gas); it is **not a
  detonation** — no reaction or energy release. The charge pressure control is a
  ratio to the ambient pressure (0.1 code) and is converted consistently. The
  front radius is measured from the azimuthally averaged density profile and its
  late-time exponent compared with the Sedov–Taylor ½.
* *Buildings*: towers are cells held at a fixed dense state each stage — an
  approximate reflecting boundary, not a wall-flux condition. The **erosion** rule
  (remove a block when the overpressure on an exposed face exceeds its strength) is
  an experimental, separately labelled feature, not structural mechanics. Debris is
  a visual overlay.
* *Shock–bubble*: post-shock state from the Rankine–Hugoniot relations; qualitative.

## 4. Smoothed-particle hydrodynamics (weakly compressible) — `solvers/sph`

Cubic-spline kernel, continuity density with δ-SPH density diffusion, Tait equation
of state (pressure clamped ≥ 0), Monaghan artificial viscosity, XSPH velocity
smoothing, dynamic boundary particles for the walls (rest-density floor at the
walls), a uniform grid for neighbour search, a velocity limiter as a safeguard.
Two-dimensional, no surface tension.

* *Still water*: hydrostatic baseline; the residual speed and surface level are tested.
* *Dam break*: front position compared with the frictionless Ritter bound 2√(gH)
  (the front lags it, as a collapsing column should); Martin & Moyce (1952) is the
  documented reference for a quantitative comparison (not automated).
* *Water-blob impact*: a 2-D blob without surface tension — not a resolved droplet splash.
* *Sloshing tank*, *pouring*: qualitative; the sloshing period sweep is the intended experiment.
* *Wave tank*: paddle wavemaker (a moving wall layer) in a **flat-bottomed** tank —
  no shoaling; three wave gauges record incident and reflected trains.
* *Floating hull*: a rigid body driven by contact forces from the water, gravity
  and damping, with limits on its motion — **not** a pressure integration over the hull.
  A still-water scene gives the equilibrium/free-decay baseline.

Energies are ½ Σ m v² with m = ρ₀ dp² (J per metre of depth); the particle count is
tracked where it changes (pouring).

## 5. Pseudo-spectral vorticity–streamfunction (FFT) — `flowzoo/spectral.py`

∂ω/∂t + u·∇ω = ν∇²ω in a periodic box; ψ from ∇²ψ = −ω; the nonlinear term is
formed in physical space with 2/3-rule dealiasing; explicit RK4 in time. Spatial
derivatives are spectrally accurate; **time integration is not exact**: with ν = 0
the energy is conserved to the RK4 truncation error (measured relative drift
≈ 2×10⁻⁹ over 200 steps), not to round-off.

* *Taylor–Green vortex*: exact decaying solution; energy compared with E₀·exp(−4νt)
  (relative error ≈ 10⁻¹⁵ in tests).
* *Kelvin–Helmholtz*, *decaying turbulence*: energy/enstrophy budgets (numerical checks).
* *Dye mixing*: a passive scalar advected by bilinear semi-Lagrangian transport with
  optional spectral diffusion κ. Stirring alone cannot reduce the variance of a
  conserved scalar; the decay seen with κ = 0 is the scheme's numerical diffusion and
  is reported as such. Diffusion-only stripes decay as exp(−2κm²t) (tests).

## 6. Reaction–diffusion (Gray–Scott) — `flowzoo/reaction.py`

∂U/∂t = D_u∇²U − UV² + F(1 − U), ∂V/∂t = D_v∇²V + UV² − (F + k)V, 9-point isotropic
Laplacian, explicit Euler with dt = 1, periodic box, reproducible seeds. The (F, k)
presets follow Pearson (1993). The scheme **clips** U and V to [0, 1] each step: a
numerical intervention that is reported, not a demonstrated property. The resemblance
of the patterns to animal markings is suggestive; the model does not establish a
biological mechanism (Kondo & Miura 2010 discuss what it can and cannot claim).

## Quantum module (experimental)

`flowzoo/quantum.py` (split-step Schrödinger) is retained as an experimental module
outside the registered gallery. Its orientation, phase colour mapping, absorbing
boundary and duration semantics have not been reviewed to the standard of the
scenes above; the unitarity test in CI is its only check.

## Diagnostics

`flowzoo/postproc.py` separates measurements (`metrics`, `series`) from plots. Each
plot's explanation states the definition, units, data source and sampling, the
assumptions and what has been checked. Frequency estimates use the solver's per-step
wake probe, require at least six oscillation cycles and a clear spectral peak, and
otherwise report "insufficient data". Absolute values are plotted with units; nothing
is normalised by its own maximum.
