"""Long-form, educational content for each exhibit — shown in the gallery.

Each entry has:
  physics : 2–4 paragraphs explaining the phenomenon and the physics in depth.
  terms   : the governing equation read symbol-by-symbol.
(Short blurb, method, numerics, validation, equation image and demo live in
engine.META.)
"""

DETAIL = {
"Wind Tunnel": {
"physics": (
"Put any object in a steady stream and the flow has to go around it. Past a "
"critical Reynolds number the boundary layers on the object's sides separate, "
"form a pair of shear layers, and those layers become unstable: one rolls up "
"into a vortex, grows until it pulls the opposite layer across the wake, sheds "
"downstream, and the process repeats on the other side. The result is a "
"staggered, periodic train of counter-rotating vortices — the von Kármán vortex "
"street.\n\n"
"Each shed vortex throws momentum sideways and pushes back on the body with a "
"force that alternates at the shedding frequency. That is why chimneys, bridge "
"decks, heat-exchanger tubes, antennas and offshore risers can suffer "
"destructive 'vortex-induced vibration', why a wire sings in the wind, and why "
"those swirling cloud streets trail downwind of islands. Swap the cylinder for a "
"square, a sharp diamond, an angled airfoil (which also generates lift), or your "
"own name, and you change where the flow separates — and so the whole wake.\n\n"
"What ties it together is the Reynolds number, Re = U·D/ν, the ratio of inertial "
"to viscous forces. Raise it and the wake goes steady → periodic shedding → "
"turbulent; the shedding frequency collapses onto a near-constant Strouhal "
"number St = f·D/U ≈ 0.2. Because lattice-Boltzmann treats the obstacle as just "
"a set of 'solid' cells, ANY shape drops in with no mesh generation — the reason "
"LBM is a workhorse for flow through geometrically complex media."),
"terms": (
"• fq — the population of fluid 'walkers' moving along lattice direction q\n"
"• cq — the discrete velocity of direction q (one of 9 in D2Q9)\n"
"• fq^eq — the local equilibrium (a discretised Maxwell–Boltzmann distribution)\n"
"• τ — the relaxation time; how fast populations relax toward equilibrium. It "
"sets the viscosity through ν = (τ − ½)/3\n"
"• left side — streaming: each population hops to the neighbouring cell\n"
"• right side — collision: populations relax toward equilibrium\n"
"• the obstacle is just the cells flagged solid — a shape, or the pixels of your text"),
},
"Rising Smoke": {
"physics": (
"Heat a parcel of fluid and it expands, becomes less dense than its "
"surroundings, and is pushed upward by buoyancy — Archimedes' principle in a "
"moving fluid. A continuous hot source therefore drives a rising column. As the "
"column rises it drags still fluid along its edges; the velocity difference "
"creates shear, the shear rolls up into vortices, and those vortices entrain "
"surrounding fluid and tangle into the turbulent, billowing structure we call a "
"plume.\n\n"
"Mathematically this is the incompressible Navier–Stokes system: conservation of "
"momentum for a fluid whose density is treated as constant except in the "
"buoyancy term (the Boussinesq approximation). The flow must also satisfy "
"incompressibility, ∇·u = 0 — locally as much fluid leaves a point as enters "
"it. That single constraint is what makes incompressible flow hard: the pressure "
"is not a thermodynamic variable here but a Lagrange multiplier that instantly "
"adjusts everywhere to keep the velocity divergence-free.\n\n"
"The same equations and solver govern visual-effects smoke, the dispersion of "
"pollutants and volcanic plumes, and ventilation and fire modelling in "
"buildings."),
"terms": (
"• u — the fluid velocity field\n"
"• ∂t u + (u·∇)u — acceleration of a fluid parcel (local + convective)\n"
"• −∇p — the pressure-gradient force that enforces incompressibility\n"
"• ν∇²u — viscous diffusion of momentum (friction)\n"
"• f_b — the buoyancy body force, proportional to temperature/dye\n"
"• ∇·u = 0 — incompressibility: the velocity field has no sources or sinks"),
},
"Mushroom Clouds": {
"physics": (
"Put a dense fluid on top of a lighter one in gravity and the configuration "
"stores potential energy it 'wants' to release by overturning. It is unstable to "
"the smallest perturbation: a tiny dip in the interface lets heavy fluid poke "
"down into light fluid, where it is even less supported, so the dip grows. Heavy "
"fluid falls in narrow spikes; light fluid rises in broad bubbles.\n\n"
"As a spike accelerates through the lighter fluid it shears against it, and that "
"shear is itself Kelvin–Helmholtz unstable — so the tip of each spike curls over "
"into the iconic mushroom cap, and the caps in turn shed smaller vortices. The "
"flow thus couples a large-scale buoyant overturning to a cascade of smaller "
"shear instabilities, which is why it mixes so efficiently.\n\n"
"The Rayleigh–Taylor instability is everywhere there is acceleration across a "
"density jump: the expanding remnants of supernovae, the compression of fuel in "
"inertial-confinement fusion, rising salt domes in geology, and overturning in "
"the oceans and atmosphere."),
"terms": (
"• u, ∂t u + (u·∇)u, −∇p, ν∇²u, ∇·u=0 — the incompressible Navier–Stokes terms\n"
"• −g·ρ·ŷ — the gravitational body force; heavier fluid (larger ρ) is pulled "
"down harder, which is the source of the instability\n"
"• ρ here is an advected density field carried with the flow"),
},
"Detonation": {
"physics": (
"When energy is released suddenly into a gas, the gas cannot get out of the way "
"fast enough: it piles up into a shock wave — an almost discontinuous jump in "
"pressure, density, temperature and velocity that travels faster than the local "
"speed of sound. Behind the leading shock the gas expands and cools through a "
"rarefaction, leaving a low-density, low-pressure cavity at the centre. This is "
"the blast-wave problem, the prototype for explosion safety, sonic booms and "
"astrophysical shocks.\n\n"
"Compressible flow is governed by the Euler equations — conservation of mass, "
"momentum and energy — written as a hyperbolic system of conservation laws. "
"Because their solutions can form genuine discontinuities, you cannot simply use "
"central differences (they would oscillate wildly at the shock). Instead the "
"physics of how waves propagate must be built into the numerical method, which "
"is what a Riemann solver does at every cell face.\n\n"
"The 'schlieren' view mimics a classic laboratory technique that makes density "
"gradients visible, so the shock fronts light up as sharp bright lines."),
"terms": (
"• U — the vector of conserved quantities: density ρ, momentum ρu and ρv, and "
"total energy E\n"
"• F(U) — the flux of those quantities (how much mass, momentum and energy cross "
"a face)\n"
"• ∂t U + ∇·F(U) = 0 — conservation: whatever leaves one cell enters its "
"neighbour, so shocks are captured correctly\n"
"• γ = 1.4 — the ratio of specific heats for air, closing the system via the "
"ideal-gas energy relation"),
},
"Shockwave Strike": {
"physics": (
"A shock wave moving through air meets a bubble of a different (here lighter) "
"gas. Two things happen. First, the shock travels faster in the light gas, so it "
"bends and focuses as it crosses the bubble. Second — and this is the key "
"mechanism — the bubble's interface is a density gradient, while the shock is a "
"pressure gradient, and where those two gradients are misaligned the equations "
"generate vorticity. This is the baroclinic torque, ∝ ∇ρ × ∇p.\n\n"
"That deposited vorticity rolls the bubble up into a pair of counter-rotating "
"vortices and stirs the two gases together. This shock-bubble interaction is the "
"canonical model of the Richtmyer–Meshkov instability — the impulsive cousin of "
"Rayleigh–Taylor — which controls mixing in supersonic combustion (scramjets) "
"and is a central obstacle in inertial-confinement fusion, where it spoils the "
"symmetry of the imploding fuel.\n\n"
"It is solved with exactly the same compressible Euler / HLLC machinery as the "
"explosion; only the initial condition differs."),
"terms": (
"• U, F(U), ∂t U + ∇·F(U) = 0, γ — the compressible Euler conservation laws "
"(see the Explosion exhibit)\n"
"• the new ingredient is purely in the initial condition: a circular region of "
"low-density gas struck by an incoming post-shock state\n"
"• baroclinic vorticity generation, ∝ ∇ρ×∇p, is what rolls the bubble up"),
},
"The Big Splash": {
"physics": (
"Hold back a column of water with a wall, remove the wall instantly, and gravity "
"converts the column's potential energy into a fast horizontal surge. The front "
"races along the floor, climbs the opposite wall, and overturns into a breaking "
"jet. The free surface — the moving air–water boundary — folds over on itself, "
"which is exactly the kind of large deformation and topology change that is "
"painful for grid-based methods.\n\n"
"Smoothed-Particle Hydrodynamics takes a completely different, mesh-free view: "
"the fluid is represented by a cloud of particles that carry mass and velocity "
"and move with the flow (a Lagrangian description). Any continuous field — "
"density, pressure, their gradients — is reconstructed at a particle by a "
"smoothed, weighted sum over its neighbours within a smoothing length, using a "
"bell-shaped kernel W. Because the particles simply follow the water, the free "
"surface is wherever the particles happen to be — no interface tracking "
"required.\n\n"
"Pressure is obtained from a stiff equation of state (weakly-compressible SPH): "
"the fluid is treated as very slightly compressible so that small density "
"changes produce the large pressures that resist compression. SPH is widely used "
"for violent free-surface flows in coastal, marine and flood engineering."),
"terms": (
"• vi — velocity of particle i; Dvi/Dt is its acceleration following the flow\n"
"• mj — mass of neighbour particle j\n"
"• pi, pj — pressures (from the Tait equation of state); ρi, ρj — densities\n"
"• ∇Wij — gradient of the smoothing kernel between particles i and j; it carries "
"the pressure force along the line joining them\n"
"• Πij — Monaghan artificial viscosity, added for stability at shocks/impacts\n"
"• g — gravity, the driving body force"),
},
"Cloud Billows": {
"physics": (
"Whenever two fluid layers slide past each other at different velocities, the "
"shear layer between them is unstable: a small wavy perturbation on the "
"interface speeds the flow over its crests and slows it in its troughs, and by "
"Bernoulli's principle the resulting pressure differences amplify the wave. The "
"wave then rolls over into a regular row of spiral vortices — the "
"Kelvin–Helmholtz billows. Neighbouring billows pair up and merge, growing the "
"layer and feeding a cascade toward two-dimensional turbulence.\n\n"
"You can see these billows directly in the wave-like 'KH cloud' formations in "
"the sky, in the cloud bands of Jupiter, and in the mixing layers of the ocean, "
"the atmosphere, jet engines and stellar winds. In two dimensions the turbulence "
"is special: energy flows from small scales to large (the inverse cascade) while "
"enstrophy flows down to small scales, the opposite of 3D turbulence.\n\n"
"This exhibit is solved with a pseudo-spectral method, which represents the flow "
"as a sum of Fourier modes (sine/cosine waves). Derivatives become simple "
"multiplications in Fourier space, so the method is extremely accurate — the gold "
"standard for smooth, periodic turbulence problems."),
"terms": (
"• ω — the vorticity (the local spin of the fluid), the quantity being evolved\n"
"• u — velocity, recovered from the streamfunction ψ\n"
"• ∂t ω + (u·∇)ω — transport of vorticity by the flow\n"
"• ν∇²ω — viscous diffusion of vorticity\n"
"• ∇²ψ = −ω — the streamfunction ψ is obtained from vorticity by inverting the "
"Laplacian (a simple division in Fourier space), then u = (∂ψ/∂y, −∂ψ/∂x)"),
},
}
