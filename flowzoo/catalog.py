"""Gallery catalog — every scene, grouped by numerical method.

Each scene is one concrete demo: which exhibit + parameter preset to run, a
display name, a one-paragraph scene description, and the gallery clip. The
gallery browses method → scene; the Studio opens any scene with its preset.
"""

# method → (scientific subtitle, list of scenes)
SCENES = [
    # ───────── Lattice-Boltzmann ─────────
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_cylinder",
     "name": "Kármán Vortex Street", "preset": {"obstacle": "Cylinder", "reynolds": 180},
     "blurb": "A circular cylinder in a steady stream. Past Re≈90 the wake can no longer stay "
              "attached and sheds a staggered train of counter-rotating vortices — the von "
              "Kármán street that sings in wires and shakes chimneys. The shedding settles onto a "
              "Strouhal number of about 0.2 (see the Plots in the player)."},
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_airfoil",
     "name": "Airfoil at Angle", "preset": {"obstacle": "Airfoil", "angle": 14, "reynolds": 400},
     "blurb": "A NACA-style airfoil at a positive angle of attack. The flow accelerates over the "
              "suction side and separates near the trailing edge, generating lift and a deflected "
              "wake — the same mechanism that holds an aircraft up."},
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_name",
     "name": "Flow Around Your Name", "preset": {"obstacle": "Your text", "text": "Funoos", "reynolds": 220},
     "blurb": "Because lattice-Boltzmann treats any obstacle as just a set of solid cells, you can "
              "drop the pixels of your own name into the tunnel and watch the wake braid around "
              "every letter — no mesh generation at all."},
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_f1",
     "name": "F1 Car Aerodynamics", "preset": {"obstacle": "F1 car", "reynolds": 320, "speed": 0.06},
     "blurb": "A Formula-1 silhouette in the tunnel — nose into the wind. The flow accelerates over "
              "the body, separates off the wheels and rear wing, and trails a broad, unsteady wake. "
              "Because the obstacle is just solid cells, the whole open-wheel shape drops straight in "
              "with no mesh — the essence of automotive aero on a lattice."},
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_cyclist",
     "name": "Cyclist in the Wind", "preset": {"obstacle": "Cyclist", "reynolds": 320, "speed": 0.07},
     "blurb": "A rider in an aero tuck. Most of a cyclist's effort goes into pushing air aside, so "
              "the tunnel shows exactly where it hurts: a high-pressure front and a wide, turbulent "
              "wake of shed vortices dragging along behind."},
    {"method": "Lattice–Boltzmann", "exhibit": "Wind Tunnel", "key": "lbm_peloton",
     "name": "Drafting (Two Riders)", "preset": {"obstacle": "Peloton (drafting)", "reynolds": 500, "speed": 0.09},
     "blurb": "Two riders, nose to tail. The second sits inside the leader's wake, where the flow is "
              "slow and sheltered — you can see the low-speed pocket that makes drafting save roughly "
              "a third of a rider's effort. The peloton, explained by the wake."},
    {"method": "Lattice–Boltzmann", "exhibit": "Porous Flow", "key": "porous_phi60",
     "name": "Flow Through Porous Rock", "preset": {"porosity": 0.60, "grain": 0.035},
     "blurb": "Fluid driven through a packed bed of grains, winding along tortuous pore paths. "
              "Funoos resolves the pore-scale flow and reads off the permeability k directly "
              "(k = ν⟨u⟩/g) — the same 'digital rock physics' used for reservoirs and filters. "
              "❖ built on the LBM permeability work behind Funoos."},
    # ───────── Navier–Stokes (projection) ─────────
    {"method": "Incompressible Navier–Stokes", "exhibit": "Rising Smoke", "key": "ns_smoke",
     "name": "Rising Smoke Plume", "preset": {"source": 1.7, "buoyancy": 0.0022, "confinement": 7},
     "cmap": "Smoke (mono)",
     "blurb": "A broad, cool column of smoke rising from a wide source. Buoyancy lifts it; shear "
              "along the edges rolls it into vortices that entrain the surroundings and tangle "
              "into a turbulent, billowing plume — the canonical buoyancy-driven flow."},
    {"method": "Incompressible Navier–Stokes", "exhibit": "Mushroom Clouds", "key": "ns_rt",
     "name": "Rayleigh–Taylor Fingers", "preset": {"atwood": 0.7},
     "blurb": "Heavy fluid resting on light fluid in gravity. The interface is unstable: heavy "
              "spikes fall, light bubbles rise, and each finger curls into the iconic mushroom "
              "cap. The Atwood number sets how violently it overturns."},
    {"method": "Incompressible Navier–Stokes", "exhibit": "Candle Flame", "key": "ns_flame",
     "name": "Candle Flame", "preset": {"buoyancy": 0.012, "zst": 0.16, "source": 0.7, "confinement": 4, "viscosity": 6e-4},
     "cmap": "Ember (fire)",
     "blurb": "A true laminar diffusion flame: fuel vapour rises from the wick, air diffuses in from "
              "the sides, and they burn on the thin stoichiometric sheet between them. The heat there "
              "makes the gas buoyant, which anchors the teardrop and sheds a vortex that flickers the "
              "tip. Combustion, not a recoloured plume. ❖ the heart of Funoos (فانوس, the lantern)."},
    {"method": "Incompressible Navier–Stokes", "exhibit": "Rayleigh-Benard", "key": "ns_rb",
     "name": "Rayleigh–Bénard Convection", "preset": {"buoyancy": 0.006, "viscosity": 0.0006},
     "cmap": "Ember (fire)",
     "blurb": "A shallow layer heated from below and cooled from above. Past a critical temperature "
              "difference it overturns: warm fluid rises, cool fluid sinks, and the motion locks into "
              "a train of counter-rotating convection cells. Pattern formation from pure instability — "
              "the same overturning that drives weather, oceans and the mantle."},
    {"method": "Incompressible Navier–Stokes", "exhibit": "Chimney Plume", "key": "ns_chimney",
     "name": "Chimney Plume in Wind", "preset": {"buoyancy": 0.0024, "wind": 0.34, "source": 0.5, "confinement": 7},
     "cmap": "Smoke (mono)",
     "blurb": "A buoyant plume leaving a stack into a steady crosswind. Buoyancy lifts it while the "
              "wind pushes it sideways, so it bends over into the classic slanted smokestack trail. "
              "The buoyancy-versus-wind balance sets the plume rise that governs how pollution disperses."},
    # ───────── Compressible Euler (HLLC) ─────────
    {"method": "Compressible Euler", "exhibit": "Detonation", "key": "euler_blast",
     "name": "Open-Air Blast", "preset": {"scene": "Open air", "pressure": 14},
     "blurb": "A high-pressure charge bursts into still air as an almost circular shock wave, "
              "trailed by an expansion that leaves a low-density cavity behind — the textbook "
              "blast-wave problem behind explosion safety and sonic booms."},
    {"method": "Compressible Euler", "exhibit": "Detonation", "key": "euler_city",
     "name": "Shockwave Hits a City", "preset": {"scene": "Shock hits a city", "pressure": 16, "strength": 1.0},
     "blurb": "A ground burst beside two towers. The blast reflects, diffracts around the corners "
              "and leaves a sheltered shadow in their lee — and where the overpressure on an "
              "exposed face exceeds its strength, the masonry fails and is flung off as debris."},
    {"method": "Compressible Euler", "exhibit": "Shockwave Strike", "key": "euler_bubble",
     "name": "Shock Meets a Bubble", "preset": {"target": "Single bubble", "mach": 1.6, "densratio": 0.18},
     "blurb": "A shock crosses a light-gas bubble. Misaligned pressure and density gradients "
              "deposit vorticity (the baroclinic torque), rolling the bubble into a vortex pair — "
              "the Richtmyer–Meshkov instability central to supersonic mixing and fusion."},
    {"method": "Compressible Euler", "exhibit": "Shockwave Strike", "key": "euler_twin",
     "name": "Twin-Bubble Mixing", "preset": {"target": "Two bubbles", "mach": 1.8, "densratio": 0.2},
     "blurb": "Two stacked bubbles struck by the same shock. Their roll-ups interact and tangle, a "
              "vivid picture of how shock-driven mixing compounds when interfaces meet."},
    # ───────── Smoothed-Particle Hydrodynamics ─────────
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_dam",
     "name": "Dam Break", "preset": {"scene": "Dam break"},
     "blurb": "Release a held-back column of water: gravity converts its head into a fast surge "
              "that races along the floor, climbs the far wall and overturns — the classic "
              "free-surface benchmark for mesh-free water."},
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_drop",
     "name": "Droplet Crown", "preset": {"scene": "Drop & splash"},
     "blurb": "A round droplet falls into a still pool and throws up a Worthington crown, then a "
              "central jet rebounds from the crater — surface motion that grid methods struggle "
              "to track but particles handle naturally."},
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_slosh",
     "name": "Sloshing Tank", "preset": {"scene": "Sloshing tank"},
     "blurb": "A tank rocked by oscillating sideways gravity. Near the natural period the wave "
              "resonates and breaks against the walls — the sloshing loads that matter for fuel "
              "tanks and cargo ships."},
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_pour",
     "name": "Pouring a Glass", "preset": {"scene": "Pour into a glass"},
     "blurb": "A continuous stream pours from a spout and fills a tall glass, splashing as it "
              "lands and settling into a rising free surface — continuous emission in a mesh-free "
              "solver."},
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_waves",
     "name": "Ocean Swell", "preset": {"scene": "Wavy ocean"},
     "blurb": "A wavemaker paddle (a moving wall of boundary particles) drives a train of "
              "travelling waves across an ocean, which steepen and break as they shoal against "
              "the far side."},
    {"method": "Smoothed-Particle Hydrodynamics", "exhibit": "The Big Splash", "key": "sph_ship",
     "name": "Floating Ship", "preset": {"scene": "Ship on waves"},
     "blurb": "A rigid hull floats on the swell. Its heave, surge and roll emerge purely from the "
              "pressure the water exerts on the hull — a two-way fluid–structure interaction, no "
              "prescribed motion."},
    # ───────── Pseudo-spectral ─────────
    {"method": "Pseudo-spectral", "exhibit": "Cloud Billows", "key": "spec_kh",
     "name": "Kelvin–Helmholtz Billows", "preset": {"init": "Shear layers"},
     "blurb": "Two fluid layers shearing past each other. The interface rolls into a regular row "
              "of spiral billows that pair and merge — the cloud-street pattern in the sky and on "
              "Jupiter, solved with a spectrally-accurate Fourier method."},
    {"method": "Pseudo-spectral", "exhibit": "Cloud Billows", "key": "spec_decay",
     "name": "Decaying Turbulence", "preset": {"init": "Random turbulence"},
     "blurb": "A random swirl of vorticity left to evolve. Like-signed vortices merge into ever "
              "larger ones — the 2-D inverse cascade — while fine structure is ground away: the "
              "paradoxical way two-dimensional turbulence organises itself as it decays."},
    {"method": "Pseudo-spectral", "exhibit": "Ink in Motion", "key": "mix_bands",
     "name": "Chaotic Mixing of Dye", "preset": {"bands": 6},
     "blurb": "Clean stripes of dye dropped into a turbulent flow, stretched and folded into "
              "ever-finer filaments. Chaotic advection mixes far faster than diffusion alone — "
              "the same way cream laces into coffee and pollutants disperse in the sea."},
    # ───────── Reaction–Diffusion ─────────
    {"method": "Reaction–Diffusion", "exhibit": "Turing Patterns", "key": "rd_spots",
     "name": "Spots", "preset": {"pattern": "Spots"},
     "blurb": "Two chemicals, reacting and diffusing at different rates, settle from noise into a "
              "regular field of spots — Turing's 1952 idea for how a leopard gets its spots, with "
              "no template guiding them."},
    {"method": "Reaction–Diffusion", "exhibit": "Turing Patterns", "key": "rd_stripes",
     "name": "Stripes & Coral", "preset": {"pattern": "Stripes"},
     "blurb": "Shift the feed/kill balance and the spots elongate into branching stripes and "
              "coral-like ridges — the same morphology as fingerprints and brain folds."},
    {"method": "Reaction–Diffusion", "exhibit": "Turing Patterns", "key": "rd_maze",
     "name": "Labyrinth", "preset": {"pattern": "Maze"},
     "blurb": "A regime where the stripes never close into spots nor straighten into lines, but "
              "wander into an endless maze — a frozen snapshot of self-organisation."},
    {"method": "Reaction–Diffusion", "exhibit": "Turing Patterns", "key": "rd_mitosis",
     "name": "Mitosis", "preset": {"pattern": "Mitosis"},
     "blurb": "The most striking regime: blobs that grow, stretch and pinch in two — patterns "
              "that self-replicate like dividing cells, from nothing but chemistry and diffusion."},
]


def by_method():
    """Ordered {method: [scene, …]} preserving first-seen order."""
    out = {}
    for s in SCENES:
        out.setdefault(s["method"], []).append(s)
    return out


def scene(key):
    for s in SCENES:
        if s["key"] == key:
            return s
    return None
