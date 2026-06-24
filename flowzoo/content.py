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
"• ρ here is an advected density field carried with the flow\n"
"• A = (ρ_heavy − ρ_light)/(ρ_heavy + ρ_light) — the Atwood number sets the "
"density contrast across the interface; the spike growth rate scales like "
"√(A·g·k), so higher A gives faster, narrower fingers"),
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
"Two scenes share the solver. In the open air the blast is a clean, expanding "
"circular shock. 'Shock hits a city' fires a ground burst beside two solid "
"towers: the front reflects off the walls (the incident and reflected shocks can "
"merge into a stronger 'Mach stem' near the ground), diffracts around the "
"corners, and leaves a quiet shadow zone in the lee of each building — the same "
"reasoning blast-protection engineering is built on.\n\n"
"The towers can also break. Each block carries a strength; when the local "
"overpressure on an exposed face exceeds it, the block fails, turns to gas (the "
"flow floods the gap) and is flung off as glowing debris on a ballistic arc. "
"Because only exposed faces feel the load, damage propagates inward from the "
"windward side — the towers are scoured front-first and visibly change shape as "
"the shock passes, leaving a sheltered stump in the lee. This is an "
"overpressure-failure model (fluid–structure coupling through the gas pressure), "
"not a full stress-and-fracture solid-mechanics simulation, but it captures why "
"blast damage is so directional.\n\n"
"The 'schlieren' view mimics a classic laboratory technique that makes density "
"gradients visible, so the shock fronts light up as sharp bright lines; the "
"Speed view shows the gas velocity, where you can watch the flow accelerate "
"around and pile up against the buildings."),
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
"(see the Detonation exhibit)\n"
"• M_s — the shock Mach number you set; the post-shock density, pressure and "
"velocity follow from the exact Rankine–Hugoniot jump conditions, so a stronger "
"shock means a hotter, faster, more compressed incoming flow\n"
"• ρ_bub/ρ_air — the bubble-to-air density ratio: below 1 the bubble is light "
"(the shock speeds through and it rolls up fast), above 1 it is heavy (the shock "
"focuses inside it); this ratio sets the sign and size of the baroclinic torque\n"
"• baroclinic vorticity generation, ∝ ∇ρ×∇p, is what rolls the bubble up"),
},
"The Big Splash": {
"physics": (
"This exhibit runs six free-surface scenes from one solver — pick from the "
"'Scene' control: a dam break, a block dropped into a pool, a sloshing tank, "
"pouring water into a glass, a wavemaker driving an ocean of waves, and a "
"rigid ship floating on those waves. Each scene exposes its own controls (drop "
"size and release height, slosh strength and period, spout width and pour speed, "
"wave height and period, ship size), so you can dial in the physics that matters "
"for that scenario.\n\n"
"Take the dam break: hold back a column of water with a wall, remove the wall "
"instantly, and gravity converts the column's potential energy into a fast "
"horizontal surge. The front races along the floor, climbs the opposite wall, "
"and overturns into a breaking jet. The free surface — the moving air–water "
"boundary — folds over on itself, exactly the kind of large deformation and "
"topology change that is painful for grid-based methods.\n\n"
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
"• g — gravity, the driving body force\n"
"• the walls are dynamic boundary particles: a fixed layer that feels the fluid "
"pressure through the same equation of state and pushes back — a physical wall, "
"not a penalty force, so the water near the walls behaves like the bulk"),
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
"Turing Patterns": {
"physics": (
"In 1952 Alan Turing proposed that the patterns of nature — a leopard's spots, a "
"zebra's stripes, the whorls of a seashell — could arise spontaneously from two "
"chemicals that react and diffuse, with no blueprint guiding them. The trick is "
"differential diffusion: a slowly-spreading 'activator' locally amplifies itself "
"while a fast-spreading 'inhibitor' suppresses it nearby. Local growth plus "
"long-range suppression carves a regular length scale out of a uniform soup.\n\n"
"The Gray–Scott model is the classic two-chemical realisation. U is fed in "
"steadily; the reaction U + 2V → 3V converts it to V (V autocatalyses); V slowly "
"decays. Tiny initial noise grows into structure, and the precise balance between "
"the feed rate F and the kill rate k decides which structure: isolated spots, "
"labyrinthine stripes, or — astonishingly — blobs that grow, pinch in two and "
"replicate like dividing cells.\n\n"
"The same activator–inhibitor mathematics models animal coat markings, the "
"spacing of hair follicles and the ridges of fingerprints, vegetation patterns in "
"arid landscapes, and chemical waves in the lab."),
"terms": (
"• U, V — the two reacting/diffusing chemical concentrations\n"
"• Du, Dv — their diffusion rates; the pattern needs Du > Dv (activator V spreads slower)\n"
"• U V² — the autocatalytic reaction that converts U into V\n"
"• F(1−U) — the steady feed replenishing U\n"
"• (F+k)V — feed plus kill removing V\n"
"• ∇² — the Laplacian (diffusion); a 9-point isotropic stencil here"),
},
"Quantum Ripples": {
"physics": (
"In quantum mechanics a particle has no definite position; it is described by a "
"complex wavefunction ψ whose squared magnitude |ψ|² is the probability of finding "
"it at each point. The wavefunction evolves by the Schrödinger equation, the "
"quantum counterpart of Newton's law — and because it is a wave, it does things a "
"classical particle never could.\n\n"
"Send a wavepacket at a barrier taller than its energy and part of it leaks "
"through — quantum tunnelling, the effect behind radioactive decay, the scanning "
"tunnelling microscope and flash memory. Send it through two slits and it "
"interferes with itself, building the striped pattern that proves matter is wave-"
"like. Leave it free and it inexorably spreads; trap it in a parabolic well and it "
"sloshes back and forth as a coherent state.\n\n"
"The phase view colours arg(ψ): the swirling bands are the wavefronts whose "
"spacing is the de Broglie wavelength, and whose bending is momentum changing."),
"terms": (
"• ψ — the complex wavefunction; |ψ|² (shown) is the probability density\n"
"• iℏ ∂t ψ — the quantum 'time derivative' (i makes evolution a rotation in the "
"complex plane, hence waves)\n"
"• −ℏ²/2m ∇²ψ — the kinetic-energy operator (curvature of ψ)\n"
"• V(x) ψ — the potential: a barrier, a slitted wall, or a harmonic well\n"
"• split-step: evolve V and the kinetic term in turn — the latter is diagonal in "
"Fourier space, so an FFT makes it a multiply"),
},
"Ink in Motion": {
"physics": (
"Stir a drop of cream into coffee and it doesn't simply diffuse — the swirls "
"stretch it into long thin ribbons, fold them over, stretch again, until the "
"ribbons are so fine that the last bit of molecular diffusion finishes the job in "
"an instant. This is chaotic advection: mixing done by the flow's stretching and "
"folding, not by diffusion. It is exponentially faster than diffusion alone, which "
"is why stirring works.\n\n"
"Here a turbulent 2-D velocity field (from the same spectral solver as the cloud "
"billows) carries a passive dye that starts as clean stripes. The dye doesn't "
"change the flow — it just goes along for the ride — so it traces the flow's "
"invisible stretching, revealing the filamentary, self-similar structure that "
"chaotic stirring always produces. The same process disperses pollutants in the "
"ocean, ash in the atmosphere, and plankton across the sea surface.\n\n"
"Because the dye is merely transported, total dye is conserved as the filaments "
"thin — mixing redistributes, it doesn't create or destroy."),
"terms": (
"• c — the dye concentration (a passive scalar; it does not affect the flow)\n"
"• u — the turbulent velocity stirring it, from the spectral solver\n"
"• (u·∇)c — advection: the flow carrying the dye and stretching it into filaments\n"
"• κ∇²c — molecular diffusion, small, smoothing only the very finest filaments\n"
"• ∇·u = 0 — the stirring flow is incompressible (area-preserving)"),
},
"Porous Flow": {
"physics": (
"Soils, rocks, filters, catalyst beds, even bone — all are porous: solid matrices "
"threaded by pore space. When you drive fluid through, it cannot go straight; it "
"winds through the connected pores, speeding up in the throats and stalling in the "
"dead ends. Henry Darcy discovered in 1856, while engineering Dijon's water "
"supply, that despite this complexity the average flow rate is simply proportional "
"to the pressure gradient. The proportionality constant — the permeability k — "
"packs all the pore geometry into one number with units of area.\n\n"
"Permeability is what petroleum engineers need to predict oil recovery, what "
"hydrologists need for groundwater, and what battery and fuel-cell designers tune "
"in porous electrodes. You cannot read k off a photo of the pores; you have to "
"solve the flow. 'Digital rock physics' does exactly that — simulate the "
"pore-scale flow in a 3D/2D image of the material and measure the averaged "
"response. That is precisely what this exhibit does with lattice-Boltzmann.\n\n"
"Here a constant body force drives flow through a random grain pack in a periodic "
"box; once steady, the volume-averaged velocity ⟨u⟩ gives k = ν⟨u⟩/g. Drop the "
"porosity and the tortuous paths choke down — permeability falls steeply, as the "
"Kozeny–Carman relation predicts."),
"terms": (
"• ⟨u⟩ — the velocity averaged over the whole sample (Darcy/superficial velocity)\n"
"• k — permeability: the area-dimensioned measure of how easily fluid passes\n"
"• μ = ρν — dynamic viscosity; ∇p — the driving pressure gradient (here a body force)\n"
"• φ — porosity, the void fraction; k climbs steeply with φ\n"
"• Kozeny–Carman: k ≈ φ³d²/[180(1−φ)²] links k to porosity and grain size d"),
},
}


# Detail text for the two newest exhibits (physics + symbol-by-symbol terms).
DETAIL["Rayleigh-Benard"] = {
"physics": (
"Heat a thin layer of fluid from below and cool it from above. At small temperature "
"differences the heat simply conducts upward and nothing moves. But warm fluid is "
"lighter, and once the temperature difference passes a critical threshold the layer "
"can no longer sit still: buoyancy wins over the viscous and diffusive damping, and "
"the fluid overturns.\n\n"
"The overturning is not chaotic at onset — it self-organises into a regular array of "
"counter-rotating rolls, warm fluid rising on one side of each cell and cool fluid "
"sinking on the other. Push the forcing higher (a larger Rayleigh number) and the "
"tidy rolls give way to unsteady, plume-shedding convection. Rayleigh–Bénard is the "
"canonical example of pattern formation from instability, and the same buoyant engine "
"drives the atmosphere, the oceans, a pot of boiling water and the Earth's mantle.\n\n"
"How much the convection beats plain conduction is measured by the Nusselt number Nu "
"(the ratio of total to conductive heat transport): below onset Nu = 1, and it climbs "
"as the rolls strengthen. Once convection takes over, the interior becomes nearly "
"uniform in temperature and almost all of the temperature drop is squeezed into thin "
"thermal boundary layers right at the hot and cold plates — which is exactly what the "
"mean-temperature plot in the player shows. The cells are typically about as wide as "
"the fluid layer is deep."),
"terms": (
"• ∂t T + u·∇T = κ∇²T — temperature is carried by the flow and diffuses with κ\n"
"• α g T ŷ — Boussinesq buoyancy: warm fluid (high T) feels an upward force\n"
"• ν∇²u — viscous damping; with κ it resists the overturning\n"
"• Rayleigh number Ra = αgΔT d³/(νκ) — forcing ÷ damping; convection begins past Ra≈1708\n"
"• fixed-temperature plates top & bottom set ΔT across the layer depth d"),
}
DETAIL["Chimney Plume"] = {
"physics": (
"A buoyant plume leaves a stack into a steady horizontal wind. Right at the source "
"buoyancy dominates and the hot, dyed fluid shoots almost straight up. But the "
"crosswind never stops pushing, so a little higher the plume bends over and trails "
"away downwind in the familiar slanted smokestack shape.\n\n"
"How high it climbs before levelling off — the 'plume rise' — is a tug-of-war between "
"the buoyancy lifting it and the wind's momentum sweeping it sideways. Strengthen the "
"wind and the plume bends sooner and stays lower; increase the buoyancy and it punches "
"higher first. That balance is exactly what engineers estimate when they size a "
"smokestack and predict how far a pollutant travels before it reaches the ground.\n\n"
"As a rule of thumb the plume rise grows with the source's buoyancy and shrinks as the "
"wind speeds up (the idea behind the Briggs plume-rise formulas used in air-quality "
"models): a tall, buoyant, slow-wind plume stays high and dilutes before it descends, "
"while a strong crosswind bends it down early and brings it to ground sooner. The "
"trajectory plot in the player traces exactly this bend-over."),
"terms": (
"• (u·∇)u — advection: the mean wind carries the plume downstream\n"
"• f_b = αg T ŷ — Boussinesq buoyancy from the hot, dyed source lifts the plume\n"
"• ν∇²u — viscous diffusion; ∇·u = 0 — incompressibility (the pressure projection)\n"
"• velocity inlet (the wind) on the left, open outflow on the right, open top\n"
"• plume rise ∝ buoyancy ÷ wind — the trade-off that sets the bent-over trajectory"),
}

# Initial & boundary conditions per exhibit — shown as a "Setup" block on each scene.
SETUP = {
"Wind Tunnel": {
  "ic": "Fluid at rest; a uniform inflow is ramped up to the chosen speed.",
  "bc": "Velocity inlet on the left, zero-gradient outflow on the right, periodic top and "
        "bottom walls, and no-slip half-way bounce-back on the obstacle (any shape, vehicle "
        "or text) — so no mesh is ever generated."},
"Rising Smoke": {
  "ic": "Quiescent ambient fluid with no dye; the source switches on at t = 0.",
  "bc": "No-penetration (free-slip) floor carrying a hot, dyed source patch; free-slip side "
        "walls; open (zero-gradient) top so the plume can leave the domain."},
"Mushroom Clouds": {
  "ic": "Heavy fluid resting on light fluid, separated by a small multi-mode interface "
        "ripple; everything at rest.",
  "bc": "Closed, no-penetration top and bottom; free-slip side walls — a sealed box."},
"Rayleigh-Benard": {
  "ic": "A linear hot-bottom-to-cold-top temperature profile at rest, plus a tiny "
        "perturbation that breaks the symmetry and selects the cell size.",
  "bc": "Fixed hot plate below and cold plate above (Dirichlet temperature); insulating, "
        "no-penetration side walls."},
"Chimney Plume": {
  "ic": "A uniform crosswind already blowing across a box of clean air.",
  "bc": "Velocity inlet (the wind) on the left, zero-gradient outflow on the right, a "
        "no-penetration (free-slip) floor with a hot dyed stack source, open top."},
"Detonation": {
  "ic": "Ambient gas at rest with a small high-pressure, high-density charge; the 'city' "
        "scene also places two solid towers on the ground.",
  "bc": "Non-reflecting (transmissive) outflow at the domain edges; solid reflecting walls "
        "on the towers, which the blast diffracts around and reflects off."},
"Shockwave Strike": {
  "ic": "A planar incident shock travelling into still gas, set just upstream of a lighter "
        "(or heavier) gas bubble at rest; the twin-bubble variant seeds two.",
  "bc": "The incident shock is set as an initial condition (a post-shock slab); all domain "
        "edges are transmissive (zero-gradient) outflow; the bubble is "
        "a density contrast, not a wall, so the shock passes through and deforms it."},
"The Big Splash": {
  "ic": "A body of water at rest under gravity — a tall column (dam break), a falling blob "
        "(droplet), a filled tank (slosh), a partly-filled glass (pour) or a wave train.",
  "bc": "Free-slip (non-penetration) tank walls enforced by dynamic boundary particles; a free surface "
        "open to the air; the ship scene adds a rigid body that floats on the surface through a "
        "contact (penalty) force, heaving and rolling with the waves."},
"Cloud Billows": {
  "ic": "Two opposing shear layers with a seeded perturbation (Kelvin–Helmholtz), or a "
        "random divergence-free field (decaying turbulence).",
  "bc": "Periodic in both directions — the natural setting for the pseudo-spectral (FFT) solver."},
"Porous Flow": {
  "ic": "Fluid at rest inside a random grain pack.",
  "bc": "Periodic in x and y with a constant body force driving the flow; no-slip bounce-back "
        "on every grain surface."},
"Turing Patterns": {
  "ic": "A uniform field (u = 1, v = 0) with a few small seeded patches of v to nucleate the pattern.",
  "bc": "Periodic in both directions; the feed and kill rates select the regime "
        "(spots, stripes, labyrinth or mitosis)."},
"Ink in Motion": {
  "ic": "A smooth random vorticity field stirring blobs of passive dye.",
  "bc": "Periodic in both directions (pseudo-spectral); the dye is advected by, but does not "
        "alter, the flow."},
"Quantum Ripples": {
  "ic": "A localized Gaussian wave packet with an initial momentum.",
  "bc": "An absorbing boundary (or a harmonic well for the closed, norm-conserving case)."},
}


# Candle flame — a low-Mach laminar diffusion flame (distinct from the smoke plume).
DETAIL["Candle Flame"] = {
"physics": (
"A candle does not burn like a campfire log; it is a laminar diffusion flame. Heat melts "
"and vaporises wax at the wick, the fuel vapour rises, and oxygen from the surrounding air "
"diffuses inward to meet it. Fuel and oxidiser can only react where they coexist in the right "
"ratio, so the burning is confined to a thin sheet — the stoichiometric surface — that wraps "
"around the rising fuel like a sock.\n\n"
"All the heat is released on that sheet. It makes the gas there much lighter, so buoyancy "
"shoots it upward; the rising column drags in fresh air at the base, which feeds the flame and "
"anchors it to the wick. That same buoyant acceleration is unstable: a ring of vorticity forms "
"and sheds periodically, pinching the flame and making the tip flicker at a few cycles a second. "
"The slender teardrop, the steady anchoring, and the flicker all fall out of this fuel-meets-air-"
"plus-buoyancy picture — which is why this scene uses a combustion model, not the recoloured "
"buoyant jet of the smoke plume."),
"terms": (
"• Z — mixture fraction: 1 in the fuel from the wick, 0 in the ambient air, conserved as it mixes\n"
"• Z = Z_st — the stoichiometric surface where fuel and air meet in burning proportion (the sheet)\n"
"• T(Z) — temperature: peaks on the sheet (fast 'Burke–Schumann' chemistry) and falls either side\n"
"• f_b = β·T·ŷ — Boussinesq buoyancy: the hot sheet is light and rises\n"
"• 𝒟∇²Z — diffusion of the mixture, which sets the thickness of the luminous zone"),
}
SETUP["Candle Flame"] = {
  "ic": "Still, cool air everywhere (mixture fraction Z = 0); the wick begins releasing fuel at t = 0.",
  "bc": "A thin fuel inlet at the wick (Z → 1) on the floor; a no-penetration (free-slip) floor, free-slip side walls that "
        "let air be entrained, and an open top through which the hot products leave.",
}
