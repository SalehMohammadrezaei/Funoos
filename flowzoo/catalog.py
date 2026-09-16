"""Scene registry — every scene the gallery offers, with its stable id, purpose and
layered explanation.

A scene is one concrete experiment: an exhibit (solver family + controls) plus a
parameter preset. Each entry carries:

    key         stable identifier (never shown; used by saved setups, clips, tests)
    name        display name
    method      solver family (filter in the gallery)
    phenomenon  physical theme the gallery is organised by
    exhibit     engine.EXHIBITS entry to run
    preset      parameters that differ from the exhibit defaults
    question    the experimental question this scene is for
    status      level of quantitative checking: "analytical" (compared with an exact
                solution), "numerical" (self-consistency / convergence / reference
                value), "qualitative" (a demonstration; no quantitative claim)
    blurb       what you are seeing (two plain sentences)
    try         two or three concrete experiments with the controls
    observe     what to look at / measure
    checks      what has been checked, and the model's limits, for this scene
    refs        a few primary or authoritative references
    cmap        optional default palette

The physics, mathematical model, initial/boundary conditions and numerical method
are shared per exhibit and live in content.DETAIL / content.SETUP / engine.META;
`scene_layers(key)` assembles the full layered page.
"""
from __future__ import annotations

# ───────────────────────── references (shared) ─────────────────────────
R = {
    "williamson": "Williamson, C.H.K. (1996). Vortex dynamics in the cylinder wake. Annu. Rev. Fluid Mech. 28, 477–539.",
    "schafer": "Schäfer, M. & Turek, S. (1996). Benchmark computations of laminar flow around a cylinder. In: Flow Simulation with High-Performance Computers II, Vieweg (DFG benchmark 2D-1/2D-2).",
    "kruger": "Krüger, T. et al. (2017). The Lattice Boltzmann Method: Principles and Practice. Springer.",
    "guo": "Guo, Z., Zheng, C. & Shi, B. (2002). Discrete lattice effects on the forcing term in the lattice Boltzmann method. Phys. Rev. E 65, 046308.",
    "anderson": "Anderson, J.D. (2016). Fundamentals of Aerodynamics, 6th ed. McGraw-Hill (Kutta–Joukowski, thin-airfoil theory).",
    "bear": "Bear, J. (1972). Dynamics of Fluids in Porous Media. Elsevier (Darcy's law, Kozeny–Carman).",
    "stam": "Stam, J. (1999). Stable Fluids. SIGGRAPH 99, 121–128.",
    "fedkiw": "Fedkiw, R., Stam, J. & Jensen, H.W. (2001). Visual simulation of smoke. SIGGRAPH 01 (vorticity confinement).",
    "sharp": "Sharp, D.H. (1984). An overview of Rayleigh–Taylor instability. Physica D 12, 3–18.",
    "chandra": "Chandrasekhar, S. (1961). Hydrodynamic and Hydromagnetic Stability. Oxford (Rayleigh–Bénard onset Ra_c = 1708).",
    "briggs": "Briggs, G.A. (1975). Plume rise predictions. In: Lectures on Air Pollution and Environmental Impact Analyses, AMS.",
    "peters": "Peters, N. (2000). Turbulent Combustion. Cambridge (mixture fraction, Burke–Schumann limit).",
    "toro": "Toro, E.F. (2009). Riemann Solvers and Numerical Methods for Fluid Dynamics, 3rd ed. Springer (HLLC, exact Sod solution).",
    "sedov": "Sedov, L.I. (1959). Similarity and Dimensional Methods in Mechanics. Academic Press (blast-wave similarity).",
    "haas": "Haas, J.-F. & Sturtevant, B. (1987). Interaction of weak shock waves with cylindrical and spherical gas inhomogeneities. J. Fluid Mech. 181, 41–76.",
    "monaghan": "Monaghan, J.J. (1994). Simulating free surface flows with SPH. J. Comput. Phys. 110, 399–406.",
    "martin": "Martin, J.C. & Moyce, W.J. (1952). An experimental study of the collapse of liquid columns on a rigid horizontal plane. Phil. Trans. R. Soc. A 244, 312–324.",
    "ritter": "Ritter, A. (1892). Die Fortpflanzung der Wasserwellen. Z. Ver. Deutsch. Ing. 36, 947–954 (dry-bed dam-break solution).",
    "dean": "Dean, R.G. & Dalrymple, R.A. (1991). Water Wave Mechanics for Engineers and Scientists. World Scientific.",
    "ibrahim": "Ibrahim, R.A. (2005). Liquid Sloshing Dynamics. Cambridge.",
    "canuto": "Canuto, C., Hussaini, M.Y., Quarteroni, A. & Zang, T.A. (2006). Spectral Methods: Fundamentals in Single Domains. Springer.",
    "boffetta": "Boffetta, G. & Ecke, R.E. (2012). Two-dimensional turbulence. Annu. Rev. Fluid Mech. 44, 427–451.",
    "taylor": "Taylor, G.I. & Green, A.E. (1937). Mechanism of the production of small eddies from large ones. Proc. R. Soc. A 158, 499–521.",
    "ottino": "Ottino, J.M. (1989). The Kinematics of Mixing: Stretching, Chaos, and Transport. Cambridge.",
    "pearson": "Pearson, J.E. (1993). Complex patterns in a simple system. Science 261, 189–192.",
    "turing": "Turing, A.M. (1952). The chemical basis of morphogenesis. Phil. Trans. R. Soc. B 237, 37–72.",
    "kondo": "Kondo, S. & Miura, T. (2010). Reaction–diffusion model as a framework for understanding biological pattern formation. Science 329, 1616–1620.",
}

LBM = "Lattice–Boltzmann"; NS = "Incompressible Navier–Stokes"; EU = "Compressible Euler"
SPH = "Smoothed-Particle Hydrodynamics"; SP = "Pseudo-spectral"; RD = "Reaction–Diffusion"

# ───────────────────────── scenes ─────────────────────────
R_BEAR = R["bear"]
R_TRACER = ("Delgado, J. M. P. Q. (2007). Longitudinal and transverse dispersion in porous media. "
            "Chemical Engineering Research and Design 85(9), 1245-1252.")

SCENES = [
    # ═════════ wakes & aerodynamics ═════════
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_cylinder", "name": "Kármán Vortex Street",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Cylinder", "reynolds": 180}, "status": "numerical",
     "question": "How does the wake change with Reynolds number?",
     "blurb": "A circular cylinder in a steady stream at Re = 180. The wake is unstable and sheds a staggered "
              "train of counter-rotating vortices, and the transverse velocity at a wake probe oscillates at the "
              "shedding frequency.",
     "try": ["Lower the Reynolds number to 40 (or open the Steady Wake scene): the wake becomes a steady pair of "
             "recirculation bubbles.", "Raise it to 400–800 and watch the vortices form closer to the body and the "
             "spectrum broaden.", "Change the obstacle size and check that the Strouhal number f·D/U stays near "
             "the same value."],
     "observe": "The Strouhal spectrum in the diagnostics: one clear peak, and the Strouhal number it gives.",
     "checks": "The measured Strouhal number is compared with the reference range 0.18–0.21 for a circular cylinder "
               "at Re 100–300 (Williamson 1996). This tunnel has periodic side walls and a blockage ratio of about "
               "0.13, which raise St slightly compared with an unconfined cylinder; the DFG benchmark geometry "
               "(Schäfer & Turek 1996) is not reproduced here, so its reference values are not used.",
     "refs": [R["williamson"], R["schafer"], R["kruger"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_cylinder_steady", "name": "Steady Wake (Re 40)",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Cylinder", "reynolds": 40}, "status": "numerical",
     "question": "Below what Reynolds number does the wake stop shedding?",
     "blurb": "The same cylinder at Re = 40. Viscosity damps the instability: the flow separates but the two "
              "recirculation bubbles behind the body stay attached and symmetric.",
     "try": ["Raise Re in steps (40, 60, 90, 120) and find where the probe signal first oscillates.",
             "Compare the streamline view with the Re = 180 scene at the same size."],
     "observe": "The wake probe signal should settle to a constant (no spectral peak: 'insufficient data' is the "
                "expected verdict).",
     "checks": "Numerical check: shedding sets in near Re ≈ 47 for an unconfined cylinder (Williamson 1996); with "
               "this blockage the threshold shifts by a few units.",
     "refs": [R["williamson"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_airfoil", "name": "Airfoil at +14°",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Airfoil", "angle": 14, "reynolds": 400}, "status": "numerical",
     "question": "How do geometry and angle affect circulation, separation and signed lift?",
     "blurb": "A symmetric airfoil at a positive angle of attack. Flow accelerates over the upper surface, "
              "separates near the trailing edge, and the deflected wake carries the momentum of the lift.",
     "try": ["Open the −14° and 0° scenes: the lift coefficient should change sign and vanish respectively.",
             "Increase the angle to 20–25° and watch the separation move forward (stall).",
             "Double the Reynolds number and compare the wake-deficit drag estimate."],
     "observe": "C_l from the bound circulation (sign convention: positive = upward) and the approximate drag.",
     "checks": "Numerical check: the lift changes sign with the angle (mirror test in tests/). Lift is the "
               "Kutta–Joukowski circulation on a contour around the body; drag is a wake-deficit approximation, "
               "not a boundary-force integration, at a Reynolds number far below real aircraft.",
     "refs": [R["anderson"], R["kruger"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_airfoil_neg", "name": "Airfoil at −14°",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Airfoil", "angle": -14, "reynolds": 400}, "status": "numerical",
     "question": "Is the lift antisymmetric in the angle of attack?",
     "blurb": "The mirror image of the +14° scene. The suction side is now the lower surface and the lift "
              "coefficient should be negative with a similar magnitude.",
     "try": ["Compare C_l here with the +14° scene using Compare in the run history.",
             "Try −5° and +5° for the linear (thin-airfoil) regime where C_l ∝ angle."],
     "observe": "The sign and size of C_l; the wake deflects upward instead of downward.",
     "checks": "Numerical check: |C_l(−α)| ≈ |C_l(+α)| within the run-to-run scatter of the unsteady wake.",
     "refs": [R["anderson"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_airfoil_zero", "name": "Airfoil at 0° (baseline)",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Airfoil", "angle": 0, "reynolds": 400}, "status": "numerical",
     "question": "Does a symmetric airfoil at zero angle produce zero lift?",
     "blurb": "The symmetric airfoil aligned with the flow. The wake is symmetric and thin; any lift measured "
              "is noise from the unsteady wake crossing the circulation contour.",
     "try": ["Use this as the reference when sweeping the angle from −10° to +10° with the sweep tool."],
     "observe": "C_l should fluctuate around zero; the drag estimate is the airfoil's minimum.",
     "checks": "Numerical check: mean C_l ≈ 0 to within the fluctuation amplitude.",
     "refs": [R["anderson"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_name", "name": "Flow Around Your Name",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Your text", "text": "Funoos", "reynolds": 220}, "status": "qualitative",
     "question": "How do gaps and letter shapes redirect the flow?",
     "blurb": "The pixels of a word are solid cells in the tunnel. Because obstacles are represented on the "
              "regular lattice, any shape drops in without a body-fitted mesh, and the wake braids around every letter.",
     "try": ["Type a word with round letters (o, c) and one with sharp ones (k, z) and compare the wakes.",
             "Add spaces between letters to see jets form in the gaps."],
     "observe": "Where the flow separates on each glyph and how the individual wakes merge downstream.",
     "checks": "Qualitative demonstration. No Strouhal number is reported for text (no single reference length).",
     "refs": [R["kruger"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_f1", "name": "Car Silhouette",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "F1 car", "reynolds": 320, "speed": 0.06}, "status": "qualitative",
     "question": "Where does a bluff vehicle shape shed its wake?",
     "blurb": "A two-dimensional racing-car silhouette on a no-slip road. The flow accelerates over the body, "
              "separates at the wheels and the rear, and trails a broad unsteady wake.",
     "try": ["Compare the wake width with the cyclist scene at the same Reynolds number.",
             "Raise the speed (Re held) and watch the lattice Mach number in the derived quantities."],
     "observe": "The separation points and the wake-deficit drag estimate over time.",
     "checks": "Qualitative demonstration: a 2-D silhouette at Re ≈ 320 does not represent a real car's "
               "three-dimensional, high-Reynolds aerodynamics; the drag number is a trend indicator only.",
     "refs": [R["kruger"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_cyclist", "name": "Rider Silhouette",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Cyclist", "reynolds": 320, "speed": 0.07}, "status": "qualitative",
     "question": "How large is the wake behind a single rider?",
     "blurb": "A rider in a tucked position, as a 2-D silhouette on a road. A stagnation region forms in "
              "front and a wide wake of shed vortices trails behind.",
     "try": ["Open the Drafting scene to put a second rider in this wake.", "Change the Reynolds number."],
     "observe": "The wake width and the slipstream profile downstream.",
     "checks": "Qualitative demonstration (2-D, low Reynolds number). No real-world power figures are computed.",
     "refs": [R["kruger"]]},
    {"method": LBM, "exhibit": "Wind Tunnel", "key": "lbm_peloton", "name": "Drafting (Two Riders)",
     "phenomenon": "Wakes & aerodynamics", "preset": {"obstacle": "Peloton (drafting)", "reynolds": 500, "speed": 0.09}, "status": "qualitative",
     "question": "How does the spacing between two bodies change the wake and the drag estimate?",
     "blurb": "Two rider silhouettes nose to tail. The second sits in the leader's low-speed wake, which the "
              "slipstream profile shows as a pocket where u/U drops well below one.",
     "try": ["Compare the combined wake-deficit drag with the single-rider scene at the same Re.",
             "Raise Re to 800 and see the pocket become more unsteady."],
     "observe": "The slipstream profile along the riders' line and the combined drag estimate.",
     "checks": "Qualitative demonstration: the wake-deficit drag is an approximation and the model is 2-D; no "
               "percentage saving is claimed.",
     "refs": [R["kruger"]]},
    # ═════════ porous media ═════════
    {"method": LBM, "exhibit": "Tracer in Rock", "key": "tracer_pulse", "name": "Tracer Through Rock",
     "phenomenon": "Porous media", "preset": {"peclet": 20.0, "injection": "Pulse"}, "status": "numerical",
     "question": "How does a tracer spread as the flow carries it through a grain pack?",
     "blurb": "A slug of tracer is released across the inlet of the same grain pack the porous experiment uses, "
              "and the settled pore flow carries it. Wide channels run ahead, narrow ones lag and dead ends hold "
              "tracer back, so the plume spreads far faster than diffusion alone would manage and the outlet "
              "curve grows a long tail.",
     "try": ["Lower the Péclet number to 1 and watch the plume stay symmetric: diffusion takes over.",
             "Raise it to 200: the front steepens and the tail lengthens, but check the plot's warning about "
             "numerical diffusion at coarse grids.",
             "Change the seed only: same porosity, different channels, different arrival time."],
     "observe": "The breakthrough curve at the outlet (the flux-averaged concentration of the water leaving) and "
                "the spreading rate D_eff, both in the diagnostic plots; D_eff divided by the molecular value is the "
                "dispersion the pore structure produces.",
     "checks": "Analytical comparison for the transport step: with the flow switched off the plume variance grows "
               "as 2·D_m·t to four decimal places. The tracer is accounted for exactly (injected = left + still "
               "inside, to round-off) with grains present and an open outlet, and none enters a grain (tests/). "
               "The dispersion measurement is only meaningful above the numerical diffusion of the upwind scheme "
               "(u·dx/2), which is reported beside it.",
     "refs": [R_BEAR, R_TRACER]},
    {"method": LBM, "exhibit": "Tracer in Rock", "key": "tracer_diffusive", "name": "Diffusion-Dominated Tracer",
     "phenomenon": "Porous media", "preset": {"peclet": 1.0, "injection": "Pulse"}, "status": "numerical",
     "question": "What does transport look like when diffusion wins?",
     "blurb": "The same sample and the same flow, but the tracer diffuses as fast as the flow carries it "
              "(Péclet number of 1). The plume stays close to symmetric, the grains only slow it down, and the "
              "outlet curve has little tail.",
     "try": ["Compare the spreading rate with the Pe = 20 scene: dispersion grows with the Péclet number.",
             "Switch the injection to a continuous supply to see a smooth front instead of a slug."],
     "observe": "The spreading rate relative to the molecular value: near 1 means the grains, not the flow, set "
                "the spreading.",
     "checks": "Numerical check: at this Péclet number the measured spreading should be within a small factor of "
               "the molecular diffusivity, and the plume should stay nearly symmetric.",
     "refs": [R_BEAR]},
    {"method": LBM, "exhibit": "Tracer in Rock", "key": "tracer_front", "name": "Advancing Tracer Front",
     "phenomenon": "Porous media", "preset": {"peclet": 50.0, "injection": "Continuous supply"}, "status": "numerical",
     "question": "How sharp is the front when tracer is supplied continuously?",
     "blurb": "The inlet is held at full concentration, so instead of a slug there is a front advancing through "
              "the pore space. It is never flat: it fingers along the fastest channels and lags in the tight "
              "throats, and the outlet concentration climbs towards 1.",
     "try": ["Raise the porosity to 0.8: with wider channels the front is smoother and arrives sooner.",
             "Drive along y instead of x on the same sample and compare the arrival time."],
     "observe": "The outlet curve climbing towards 1, and how wide the rise is: a wide rise means a ragged front.",
     "checks": "Numerical check: with a steady supply the flux-averaged outlet concentration approaches the inlet "
               "value and never exceeds it (tests/); the finite-volume scheme keeps the tracer between 0 and 1, and "
               "the open outlet lets the front leave instead of filling the sample.",
     "refs": [R_BEAR]},
    {"method": LBM, "exhibit": "Porous Flow", "key": "porous_phi60", "name": "Flow Through Porous Rock",
     "phenomenon": "Porous media", "preset": {"porosity": 0.60, "grain": 0.035}, "status": "numerical",
     "question": "How readily does a grain pack transmit fluid, and why?",
     "blurb": "A force drives fluid through the connected gaps between solid grains. Narrow passages restrict "
              "the flow while wider channels carry more; once settled, the permeability k describes how readily "
              "the sample transmits fluid.",
     "try": ["Keep the porosity and change the seed (Same Porosity, Different Connectivity scene) — k changes "
             "because the pores connect differently.", "Sweep the porosity from 0.45 to 0.8 with the sweep tool.",
             "Sweep the driving strength: in the Darcy regime k must not depend on it."],
     "observe": "The permeability readout k = ν U_D/g, with U_D the flow averaged over the whole sample.",
     "checks": "Numerical check: the same solver reproduces the analytical plane-Poiseuille permeability "
               "(tests/, error 0.07 %). The Kozeny–Carman line in the plot is an empirical 3-D relation shown "
               "for orientation only; agreement with it is not claimed for this 2-D geometry.",
     "refs": [R["bear"], R["guo"], R["kruger"]]},
    {"method": LBM, "exhibit": "Porous Flow", "key": "porous_connectivity", "name": "Similar Porosity, Different Arrangement",
     "phenomenon": "Porous media", "preset": {"porosity": 0.60, "grain": 0.035, "seed": 7}, "status": "numerical",
     "question": "Why can equal porosity produce different permeability?",
     "blurb": "The same target porosity and grain size as the default sample, but a different random arrangement. "
              "The measured porosities differ slightly (about 0.598 versus 0.600 at Medium — the random pack does not "
              "hit the target exactly; both are shown in the readouts); the paths through the pore space differ much more.",
     "try": ["Compare k with the porous_phi60 scene (run history → Compare).", "Try seeds 2–10 with the sweep tool "
             "to see the spread of k at fixed porosity."],
     "observe": "The streamline view: a few wide channels carry most of the flow.",
     "checks": "Numerical check (self-consistency): compare the two measured porosities (they differ by a few hundred "
               "cells out of ~137 000) with the two permeabilities; the k difference is far larger than the porosity difference.",
     "refs": [R["bear"]]},
    {"method": LBM, "exhibit": "Porous Flow", "key": "porous_aniso", "name": "Directional Permeability",
     "phenomenon": "Porous media", "preset": {"porosity": 0.60, "grain": 0.035, "direction": "y"}, "status": "numerical",
     "question": "Does the sample conduct flow equally in different directions?",
     "blurb": "The same grain pack driven along y instead of x. The permeability tensor of a random pack is "
              "nearly isotropic; an arranged or elongated pack is not.",
     "try": ["Run with direction x and y on the same seed and compare k_x with k_y.",
             "Lower the porosity to 0.45: anisotropy of the random pack grows as fewer paths remain."],
     "observe": "k_y versus k_x in the run history.",
     "checks": "Numerical check: on a sample of horizontal solid slabs the solver gives k_x ≫ k_y (tests/), so the "
               "directional measurement is trustworthy; for a random pack k_x ≈ k_y is expected.",
     "refs": [R["bear"]]},
    # ═════════ buoyancy & convection ═════════
    {"method": NS, "exhibit": "Rising Smoke", "key": "ns_smoke", "name": "Rising Smoke Plume",
     "phenomenon": "Buoyancy & convection", "preset": {"source": 1.7, "buoyancy": 0.0022, "confinement": 7}, "cmap": "Smoke (mono)",
     "status": "qualitative", "question": "How does buoyancy turn a smooth column into a turbulent plume?",
     "blurb": "A source of buoyant, dyed fluid at the floor. The column rises, shears against the still air, "
              "rolls up into vortices and entrains its surroundings.",
     "try": ["Set the vorticity confinement to 0 to see how much of the small-scale detail is added by that "
             "model term.", "Halve the buoyancy coefficient and compare the plume-rise curve."],
     "observe": "The plume-rise diagnostic and the kinetic energy growth.",
     "checks": "Qualitative demonstration: the projection method keeps the flow divergence-free to the solver "
               "tolerance; vorticity confinement is a visual modelling term, not a physical property.",
     "refs": [R["stam"], R["fedkiw"]]},
    {"method": NS, "exhibit": "Mushroom Clouds", "key": "ns_rt", "name": "Rayleigh–Taylor Fingers",
     "phenomenon": "Buoyancy & convection", "preset": {"atwood": 0.7}, "status": "qualitative",
     "question": "How does the density contrast set the growth of the instability?",
     "blurb": "Heavy fluid rests on light fluid in gravity. The interface is unstable: spikes fall, bubbles rise, "
              "and each finger rolls up into a mushroom cap.",
     "try": ["Open the Single-Mode scene to measure the early growth of one wavelength.",
             "Change the Atwood number from 0.2 to 1.0 and compare the mixing-width curves."],
     "observe": "The mixing-layer width versus time (normalised by the initial heavy/light values).",
     "checks": "Qualitative demonstration: density only enters the buoyancy force of a constant-density projection "
               "solver (a Boussinesq-like approximation). Quantitative large-Atwood growth rates need a "
               "variable-density formulation and are not claimed.",
     "refs": [R["sharp"]]},
    {"method": NS, "exhibit": "Mushroom Clouds", "key": "ns_rt_single", "override": {"ic": 'Heavy over light with a single cosine ripple of the chosen wavenumber and small amplitude (2 % of the height); at rest.', "bc": 'Closed no-penetration top and bottom; free-slip side walls.'}, "name": "Rayleigh–Taylor, Single Mode",
     "phenomenon": "Buoyancy & convection", "preset": {"atwood": 0.5, "modes": 2, "perturbation": 1.0}, "status": "numerical",
     "question": "Can the early growth of one interface mode be measured consistently?",
     "blurb": "A single small-amplitude cosine ripple with two wavelengths across the box. One bubble and one "
              "spike per wavelength grow before the nonlinear mushroom stage.",
     "try": ["Change the wavenumber (1–4) and compare how fast the mixing width starts to grow.",
             "Repeat at a higher resolution to check the early growth is resolution-independent."],
     "observe": "The early, near-exponential part of the mixing-width curve.",
     "checks": "Numerical check (consistency across resolutions); the linear growth rate is not compared with theory "
               "because the model is Boussinesq-like and viscous.",
     "refs": [R["sharp"]]},
    {"method": NS, "exhibit": "Candle Flame", "key": "ns_flame", "name": "Candle Flame",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.012, "zst": 0.16, "source": 0.7, "confinement": 4, "viscosity": 6e-4},
     "cmap": "Ember (fire)", "status": "qualitative",
     "question": "What shapes a laminar diffusion flame and makes its tip flicker?",
     "blurb": "A simplified flame model: an advected mixture variable Z with a prescribed source velocity at "
              "the wick, a temperature proxy T(Z) that peaks on the stoichiometric surface, and buoyancy "
              "proportional to it. The teardrop shape and the tip flicker come from that coupling.",
     "try": ["Move Z_st from 0.08 to 0.30: the luminous sheet moves relative to the fuel core.",
             "Lower the buoyancy to make the flame shorter and steadier."],
     "observe": "The flame-tip height and its flicker spectrum.",
     "checks": "Qualitative demonstration. The model prescribes the wick velocity, damps the flow laterally, and "
               "uses a temperature proxy, not chemistry or heat release; it is not a combustion simulation.",
     "refs": [R["peters"]]},
    {"method": NS, "exhibit": "Rayleigh-Benard", "key": "ns_rb", "name": "Heated Layer: Convection Cells",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.006, "viscosity": 0.0006}, "cmap": "Ember (fire)",
     "status": "numerical", "question": "When does convection develop, and how does heat transport change?",
     "blurb": "A shallow layer heated from below and cooled from above. Warm fluid rises, cool fluid sinks, and "
              "the motion organises into counter-rotating cells that carry heat far faster than conduction.",
     "try": ["Open the Conduction Baseline scene (buoyancy 0): the profile stays linear and Nu = 1.",
             "Raise the thermal diffusivity κ (advanced) and watch the Nusselt number fall.",
             "Change the viscosity: the Rayleigh number in the derived quantities changes with it."],
     "observe": "The temperature profile flattening in the core and the heat-flux budget with its Nusselt number.",
     "checks": "Numerical check: with buoyancy off the diffusion step preserves the conduction profile (tests/). "
               "The Rayleigh number is computed from β·ΔT, H, ν and κ. This solver's plates are free-slip "
               "(no-penetration, no shear) and conducting, for which linear theory gives onset at Ra ≈ 657.5 "
               "(27π⁴/4); the often-quoted 1708 is for no-slip plates. At this grid Ra is far above both, so the "
               "onset regime is not reachable here.",
     "refs": [R["chandra"]]},
    {"method": NS, "exhibit": "Rayleigh-Benard", "key": "ns_rb_conduction", "override": {"ic": 'Linear hot-to-cold temperature profile at rest with a small seed ripple.', "bc": 'Fixed plate temperatures below and above; free-slip (no-penetration) plates; insulating side walls; buoyancy switched off.'}, "name": "Heated Layer: Conduction Baseline",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.0, "viscosity": 0.0006}, "cmap": "Ember (fire)",
     "status": "analytical", "question": "What does pure conduction look like?",
     "blurb": "The same layer with the buoyancy switched off. Nothing moves; heat crosses the layer by "
              "conduction only and the temperature profile stays linear.",
     "try": ["Increase the seed ripple: the perturbation decays instead of growing.",
             "Compare the heat-flux plot with the convecting scene."],
     "observe": "A straight temperature profile and a Nusselt number of 1.",
     "checks": "Analytical comparison: the steady conduction profile is linear and the total flux equals κΔT/H "
               "(Nu = 1); tested in tests/test_numerics.py.",
     "refs": [R["chandra"]]},
    {"method": NS, "exhibit": "Rayleigh-Benard", "key": "ns_rb_vigorous", "name": "Heated Layer: Vigorous Convection",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.012, "viscosity": 0.0002}, "cmap": "Ember (fire)",
     "status": "numerical", "question": "How does the heat transport change as the Rayleigh number grows?",
     "blurb": "Stronger buoyancy and lower viscosity: the cells break into unsteady plumes and the thermal "
              "boundary layers at the plates thin.",
     "try": ["Compare the Nusselt number with the moderate scene.", "Increase the resolution to resolve the thinner plumes."],
     "observe": "Thinner boundary layers in the temperature profile; a higher Nusselt number.",
     "checks": "Numerical check (Nu increases with Ra); no scaling law is claimed at this resolution.",
     "refs": [R["chandra"]]},
    {"method": NS, "exhibit": "Chimney Plume", "key": "ns_chimney", "name": "Plume in a Crosswind",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.0022, "wind": 0.45, "source": 0.5, "confinement": 7},
     "cmap": "Smoke (mono)", "status": "qualitative",
     "question": "How does the plume trajectory change with wind speed?",
     "blurb": "A buoyant plume leaves a stack into a steady crosswind. Buoyancy lifts it while the wind bends "
              "it over, giving the slanted trail whose height sets how a pollutant disperses.",
     "try": ["Open the Calm Air scene (wind 0) and the Strong Wind scene (0.55) with the same source and compare "
             "the trajectories.", "Sweep the wind from 0 to 0.5 with the sweep tool."],
     "observe": "The plume centre-line height versus downwind distance.",
     "checks": "Qualitative demonstration: the rise falls as the wind increases, the trend of plume-rise theory "
               "(Briggs); no quantitative rise formula is verified.",
     "refs": [R["briggs"]]},
    {"method": NS, "exhibit": "Chimney Plume", "key": "ns_chimney_calm", "name": "Plume in Calm Air",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.0022, "wind": 0.0, "source": 0.5, "confinement": 7},
     "cmap": "Smoke (mono)", "status": "qualitative", "question": "What does the same source do without wind?",
     "blurb": "The same stack and source with no crosswind. The plume rises vertically and meanders only "
              "through its own instability.",
     "try": ["Compare with the crosswind scenes in the run history."],
     "observe": "A near-vertical trajectory in the diagnostics.",
     "checks": "Qualitative demonstration (reference case for the wind sweep).",
     "refs": [R["briggs"]]},
    {"method": NS, "exhibit": "Chimney Plume", "key": "ns_chimney_strong", "name": "Plume in a Strong Wind",
     "phenomenon": "Buoyancy & convection", "preset": {"buoyancy": 0.0022, "wind": 0.55, "source": 0.5, "confinement": 7},
     "cmap": "Smoke (mono)", "status": "qualitative", "question": "How low does a strong wind hold the plume?",
     "blurb": "The same source in the strongest recommended wind. The plume bends over close to the stack "
              "and streams downwind near the ground.",
     "try": ["Compare the centre-line height with the calm and moderate scenes."],
     "observe": "The reduced plume rise.",
     "checks": "Qualitative demonstration.",
     "refs": [R["briggs"]]},
    # ═════════ shocks & compressible flow ═════════
    {"method": EU, "exhibit": "Shock Tube", "key": "euler_sod", "override": {"ic": 'Left state (ρ, u, p) = (1, 0, 1), right state (0.125, 0, 0.1), membrane at x = 0.5, gas at rest.', "bc": 'Zero-gradient ends (the waves have not reached them at the reference time 0.2).'}, "name": "Sod Shock Tube",
     "phenomenon": "Shocks & compressible flow", "preset": {}, "status": "analytical",
     "question": "Where are the shock, the contact and the rarefaction, and how large is the error?",
     "blurb": "Two gases at different pressures separated by a membrane that bursts at t = 0. A shock runs "
              "into the low-pressure gas, a contact discontinuity follows it, and a rarefaction fan spreads "
              "the other way.",
     "try": ["Raise the resolution and watch the mean density error fall.",
             "Shorten the duration to see the waves before they spread."],
     "observe": "The density and velocity profiles against the exact Riemann solution and the printed errors.",
     "checks": "Analytical comparison: the exact Riemann solution (Toro). Measured mean absolute density error "
               "≈ 0.003 at 300 cells (CI test).",
     "refs": [R["toro"]]},
    {"method": EU, "exhibit": "Detonation", "key": "euler_blast", "name": "Blast Wave in Open Air",
     "phenomenon": "Shocks & compressible flow", "preset": {"scene": "Open air", "pressure": 140}, "status": "numerical",
     "question": "How fast does a blast front expand, and how does it slow down?",
     "blurb": "A disc of high-pressure gas is released into still gas (a pressure-release model; no reaction "
              "or energy release is computed). It expands as a near-circular shock followed by a rarefaction "
              "that leaves a low-density core.",
     "try": ["Sweep the charge pressure ratio (50, 100, 200, 400) and compare the shock-radius curves.",
             "Change the charge size at fixed ratio."],
     "observe": "The shock radius versus time and its late-time power-law exponent.",
     "checks": "Numerical check: the front radius decelerates toward the Sedov–Taylor similarity exponent ½ of a "
               "2-D point blast; the same solver passes the Sod comparison. This is not a detonation model.",
     "refs": [R["sedov"], R["toro"]]},
    {"method": EU, "exhibit": "Detonation", "key": "euler_city", "name": "Blast and Buildings (held obstacles)",
     "phenomenon": "Shocks & compressible flow", "preset": {"scene": "Shock hits a city", "pressure": 160, "structure": "Rigid walls"},
     "status": "qualitative", "question": "How do boundaries alter shock propagation?",
     "blurb": "A ground burst beside two towers whose cells are held at a fixed dense state (an approximate reflecting "
              "obstacle, not an impermeable wall flux). The blast reflects off them, diffracts around the corners and "
              "leaves a sheltered zone in the lee of each building.",
     "try": ["Open the Erosion variant to see the simplified structural-failure model.",
             "Move to a lower pressure ratio to weaken the reflected fronts."],
     "observe": "Mach-stem-like merging near the ground and the shadow zones behind the towers.",
     "checks": "Qualitative demonstration: the towers are cells held at a fixed dense state each stage, an "
               "approximate reflecting boundary rather than a true wall-flux condition.",
     "refs": [R["toro"]]},
    {"method": EU, "exhibit": "Detonation", "key": "euler_city_erosion", "override": {"bc": 'Zero-gradient edges (weakly reflecting); towers held at a fixed dense state; a block is removed when the overpressure on an exposed face exceeds its strength (experimental rule).'}, "name": "Blast and Buildings (erosion, experimental)",
     "phenomenon": "Shocks & compressible flow", "preset": {"scene": "Shock hits a city", "pressure": 160, "structure": "Erodes (experimental)", "strength": 1.0},
     "status": "qualitative", "question": "What does a simplified erosion rule do to the towers?",
     "blurb": "The same burst with an experimental rule: a solid block is removed when the overpressure on an "
              "exposed face exceeds its strength, and the gas floods the gap. Debris particles are a visual "
              "overlay, not part of the solution.",
     "try": ["Raise the structure strength until the towers survive; lower it until they are scoured away."],
     "observe": "Where damage starts (windward faces) and how the shadow zones change as blocks vanish.",
     "checks": "Qualitative demonstration: this is not a structural-mechanics model; the threshold rule is a stand-in.",
     "refs": [R["toro"]]},
    {"method": EU, "exhibit": "Shockwave Strike", "key": "euler_bubble", "name": "Shock Meets a Light Bubble",
     "phenomenon": "Shocks & compressible flow", "preset": {"target": "Single bubble", "mach": 1.6, "densratio": 0.18},
     "status": "qualitative", "question": "How does the density contrast alter the interface deformation?",
     "blurb": "A planar shock crosses a bubble of lighter gas. Misaligned pressure and density gradients "
              "deposit vorticity on the interface (the baroclinic torque) and roll the bubble into a vortex pair.",
     "try": ["Open the Heavy Bubble scene (density ratio 3): the shock slows and focuses inside it instead.",
             "Raise the Mach number to 2.5."],
     "observe": "The kinetic energy jump as the shock passes and the roll-up that follows.",
     "checks": "Qualitative demonstration: the same solver passes the Sod comparison; the classic experiments "
               "(Haas & Sturtevant 1987) are cylindrical/spherical and not reproduced quantitatively here.",
     "refs": [R["haas"], R["toro"]]},
    {"method": EU, "exhibit": "Shockwave Strike", "key": "euler_bubble_heavy", "name": "Shock Meets a Heavy Bubble",
     "phenomenon": "Shocks & compressible flow", "preset": {"target": "Single bubble", "mach": 1.6, "densratio": 3.0},
     "status": "qualitative", "question": "What changes when the bubble is denser than the surrounding gas?",
     "blurb": "The same shock hitting a bubble three times denser than the gas around it. The shock slows "
              "inside the bubble and the vorticity has the opposite sense, so the interface deforms differently.",
     "try": ["Compare with the light bubble in the run history.", "Try density ratio 1.0 as the null case."],
     "observe": "The direction of the roll-up and the slower interface response.",
     "checks": "Qualitative demonstration.",
     "refs": [R["haas"]]},
    {"method": EU, "exhibit": "Shockwave Strike", "key": "euler_twin", "name": "Twin Bubbles",
     "phenomenon": "Shocks & compressible flow", "preset": {"target": "Two bubbles", "mach": 1.8, "densratio": 0.2},
     "status": "qualitative", "question": "How do two shocked interfaces interact?",
     "blurb": "Two stacked light bubbles struck by the same shock. Their roll-ups interact and tangle.",
     "try": ["Compare with the single bubble at the same Mach number."],
     "observe": "The interaction of the two vortex pairs.",
     "checks": "Qualitative demonstration.",
     "refs": [R["haas"]]},
    # ═════════ free surfaces & waves ═════════
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_rest", "override": {"ic": 'A tank filled to 42 % of its height with water at rest, on a regular particle lattice; gravity eased in over 0.4 s.', "bc": 'Fixed boundary particles for the floor and side walls; free surface open to the air; no wavemaker motion.'}, "name": "Still Water (hydrostatic baseline)",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Still water (hydrostatic)"}, "status": "numerical",
     "question": "Does water at rest stay at rest?",
     "blurb": "A tank of water with nothing to disturb it. A good particle method keeps the surface flat and the "
              "velocities near zero; residual motion measures the numerical noise of the scheme.",
     "try": ["Change the particle count and compare the residual kinetic energy.",
             "Use it as the reference for the other free-surface scenes."],
     "observe": "The kinetic energy should stay small and decay; the surface height should stay at the fill level.",
     "checks": "Numerical check: residual speed and surface level are tested in tests/ (weakly compressible SPH "
               "with density diffusion and a rest-density floor at the walls).",
     "refs": [R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_dam", "name": "Dam Break",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Dam break"}, "status": "numerical",
     "question": "How does the released potential energy drive the surge?",
     "blurb": "A held-back column of water is released. Gravity converts its head into a fast surge that races "
              "along the floor, climbs the far wall and overturns.",
     "try": ["Double the dam height and compare the front speed.", "Raise the particle count to sharpen the surge."],
     "observe": "The front position against the frictionless Ritter bound 2√(gH) in the diagnostics.",
     "checks": "Numerical check: the front lags the Ritter dry-bed limit as a collapsing column should; the classic "
               "Martin & Moyce data are the documented reference for a quantitative comparison (not automated).",
     "refs": [R["ritter"], R["martin"], R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_drop", "override": {"ic": 'A pool 30 % deep at rest and a round parcel of water released from the chosen height with zero velocity.', "bc": 'Fixed boundary particles for the floor and walls; free surface; no surface tension in the model.'}, "name": "Water-Blob Impact",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Drop & splash"}, "status": "qualitative",
     "question": "How do impact speed and size change the splash?",
     "blurb": "A round parcel of water falls into a pool and throws up a crown-like sheet and a central jet. "
              "This is a two-dimensional blob impact without surface tension, not a resolved droplet splash.",
     "try": ["Raise the release height (impact speed √(2gh)) and the blob size and compare the crown height."],
     "observe": "The crown height curve in the diagnostics.",
     "checks": "Qualitative demonstration: no surface tension, 2-D, weakly compressible.",
     "refs": [R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_slosh", "override": {"ic": 'A tank filled to 42 % at rest.', "bc": 'Fixed boundary particles for the tank; a horizontal oscillating body force of the chosen strength and period (the whole tank rocks).'}, "name": "Sloshing Tank",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Sloshing tank"}, "status": "qualitative",
     "question": "How does the response depend on the forcing frequency?",
     "blurb": "A tank rocked by an oscillating sideways acceleration. Near the tank's natural period the wave "
              "resonates and breaks against the walls.",
     "try": ["Sweep the slosh period from 0.6 to 2.4 s with a small strength (0.2 g) to find the resonance.",
             "Compare the wall run-up at the resonant and off-resonant periods."],
     "observe": "The water level at each wall over time.",
     "checks": "Qualitative demonstration; the linear natural period of a rectangular tank (Ibrahim 2005) is the "
               "documented reference for the sweep.",
     "refs": [R["ibrahim"], R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_pour", "override": {"ic": 'An empty glass; particles are emitted at the spout with the pour speed.', "bc": 'Fixed boundary particles for the glass; continuous emission at the spout (capped at 22 000 particles).'}, "name": "Pouring a Glass",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Pour into a glass"}, "status": "qualitative",
     "question": "How does a continuous stream fill a container?",
     "blurb": "Particles are emitted at a spout and fall into a tall glass, splashing as they land and settling "
              "into a rising surface.",
     "try": ["Change the pour speed and the spout width (the applied width is shown in the derived quantities)."],
     "observe": "The fill-level curve.",
     "checks": "Qualitative demonstration.",
     "refs": [R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_waves", "override": {"ic": 'A flat-bottomed tank filled to 40 % at rest.', "bc": 'The left wall layer moves as the wavemaker paddle (stroke and period as set); fixed floor and right wall; free surface; no beach, so waves reflect.'}, "name": "Wave Tank",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Wave tank"}, "status": "qualitative",
     "question": "What wavelength, amplitude and reflection does the wavemaker produce?",
     "blurb": "A paddle (a moving wall of boundary particles) drives a train of waves along a flat-bottomed tank. "
              "They reflect from the far wall; there is no sloping beach, so no shoaling.",
     "try": ["Change the period and read the wavelength from the delay between the three gauges.",
             "Halve the stroke and check the amplitude scales down."],
     "observe": "The three wave-gauge records: incident waves first, then the reflected train mixed in.",
     "checks": "Qualitative demonstration; the deep-water dispersion relation (Dean & Dalrymple) is the documented "
               "reference for the gauge-derived wavelength.",
     "refs": [R["dean"], R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_ship_still", "override": {"ic": 'Still water at 40 % fill with the rigid hull placed at the surface.', "bc": 'Fixed walls, the paddle held still (stroke 0); hull driven by contact forces from the water, gravity and damping, with motion limits.'}, "name": "Floating Hull: Still Water",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Ship on waves", "waveA": 0.0}, "status": "numerical",
     "question": "Are flotation and motion consistent with the body parameters?",
     "blurb": "The rigid hull is placed on still water with the wavemaker stopped. It should settle to its "
              "equilibrium draught and its heave and roll should decay.",
     "try": ["Change the ship size and compare the equilibrium draught.", "Then open the Floating Hull on Waves scene."],
     "observe": "Heave settling to a constant and roll decaying to zero.",
     "checks": "Numerical check: free-decay behaviour; the hull is driven by contact forces from the water, gravity "
               "and damping, with limits on its motion — not by a pressure integration over the hull.",
     "refs": [R["monaghan"]]},
    {"method": SPH, "exhibit": "The Big Splash", "key": "sph_ship", "override": {"ic": 'Water at 40 % fill at rest with the hull at the surface.', "bc": 'Moving paddle wall (wavemaker), fixed floor and right wall; hull driven by contact forces, gravity and damping, with motion limits.'}, "name": "Floating Hull on Waves",
     "phenomenon": "Free surfaces & waves", "preset": {"scene": "Ship on waves"}, "status": "qualitative",
     "question": "How does the hull respond to the wave train?",
     "blurb": "The rigid hull rides the wavemaker's waves, heaving and rolling as the surface moves beneath it.",
     "try": ["Change the wave period: the hull responds most near its own natural periods."],
     "observe": "Heave and roll records alongside the wave gauges.",
     "checks": "Qualitative demonstration (contact-force coupling with damping and motion limits).",
     "refs": [R["monaghan"]]},
    # ═════════ vortices & mixing ═════════
    {"method": SP, "exhibit": "Cloud Billows", "key": "spec_kh", "name": "Kelvin–Helmholtz Billows",
     "phenomenon": "Vortices & mixing", "preset": {"init": "Shear layers"}, "status": "numerical",
     "question": "How does a shear layer roll up, and how do the billows pair?",
     "blurb": "Two layers slide past each other. The interface rolls into a row of spiral billows that pair and "
              "merge — the pattern of billow clouds and of mixing layers.",
     "try": ["Change the perturbation amplitude: larger kicks roll up sooner.", "Thin the shear layer (advanced) to "
             "shift the most unstable wavelength."],
     "observe": "Energy stays nearly constant while enstrophy falls as billows merge.",
     "checks": "Numerical check: spatial derivatives are spectral; time stepping is explicit RK4, so with ν = 0 the "
               "energy is conserved to truncation error (measured drift ≈ 2×10⁻⁹ over 200 steps in CI), not to "
               "round-off. The Taylor–Green scene gives the analytical check of the viscous decay.",
     "refs": [R["canuto"], R["boffetta"]]},
    {"method": SP, "exhibit": "Cloud Billows", "key": "spec_decay", "override": {"ic": 'A random vorticity field with a peaked spectrum around wavenumber 14, drawn on a fixed 256² reference grid from the seed and truncated or zero-padded to the chosen resolution, so the same seed gives the same initial field at every resolution.', "bc": 'Periodic in both directions (pseudo-spectral).'}, "name": "Decaying Turbulence",
     "phenomenon": "Vortices & mixing", "preset": {"init": "Random turbulence"}, "status": "numerical",
     "question": "Why do two-dimensional eddies grow as the flow decays?",
     "blurb": "A random swirl of vorticity left to evolve. Like-signed vortices merge into larger ones — the "
              "2-D inverse energy cascade — while enstrophy is dissipated at small scales.",
     "try": ["Change the seed (advanced) for a different realisation.", "Lower the viscosity."],
     "observe": "Energy nearly conserved, enstrophy decaying.",
     "checks": "Numerical check (energy/enstrophy budgets).",
     "refs": [R["boffetta"]]},
    {"method": SP, "exhibit": "Cloud Billows", "key": "spec_tg", "override": {"physics": 'The Taylor–Green vortex is a periodic array of counter-rotating cells, ψ = sin x sin y, that is an exact solution of the two-dimensional Navier–Stokes equations: the nonlinear term vanishes for this field, so the pattern keeps its shape and every mode decays at the viscous rate 2νk² — for wavenumber 1 in a 2π box, the energy decays as exp(−4νt). That makes it a clean check of the viscous term and of the time integrator, not a demonstration of instability.', "ic": 'ω = 2 sin x sin y (wavenumber 1) at t = 0; no perturbation, no randomness.', "bc": 'Periodic in both directions (pseudo-spectral).'}, "name": "Taylor–Green Vortex",
     "phenomenon": "Vortices & mixing", "preset": {"init": "Taylor–Green vortex", "viscosity": 4e-4}, "status": "analytical",
     "question": "Does the solver reproduce the exact viscous decay, and does it improve with refinement?",
     "blurb": "A regular array of counter-rotating vortices that is an exact solution of the 2-D Navier–Stokes "
              "equations: it keeps its shape and decays as exp(−4νt).",
     "try": ["Compare Low and High resolution: the decay curve is the same.", "Change the viscosity: the decay rate "
             "follows 4ν."],
     "observe": "The measured kinetic energy against the dashed analytical curve.",
     "checks": "Analytical comparison: energy decay against E₀·exp(−4νt) (relative error ≈ 10⁻¹⁵ in tests/).",
     "refs": [R["taylor"], R["canuto"]]},
    {"method": SP, "exhibit": "Ink in Motion", "key": "mix_bands", "name": "Chaotic Mixing of Dye",
     "phenomenon": "Vortices & mixing", "preset": {"bands": 6}, "status": "qualitative",
     "question": "How much apparent mixing comes from stirring and how much from diffusion?",
     "blurb": "Stripes of dye in a turbulent flow are stretched and folded into ever-finer filaments. Stirring "
              "alone cannot reduce the variance of a conserved dye; diffusion — physical and numerical — does.",
     "try": ["Open the Diffusion Only scene (stirring 0) and the Stirring Only scene (κ = 0) and compare the "
             "variance curves.", "Change the number of bands."],
     "observe": "The dye variance versus time in the diagnostics.",
     "checks": "Qualitative demonstration: the semi-Lagrangian scheme adds numerical diffusion once filaments "
               "reach the grid scale; the three scenes separate the contributions.",
     "refs": [R["ottino"]]},
    {"method": SP, "exhibit": "Ink in Motion", "key": "mix_diffusion", "override": {"physics": 'With the stirring switched off the dye simply diffuses: each band decays at the rate κ·m² of its wavenumber m, so the fundamental of the stripes decays as exp(−κm²t) and the variance as exp(−2κm²t). This scene isolates physical diffusion from the stretching and folding of the stirred scenes.', "ic": 'Alternating horizontal dye bands (0/1) with the chosen number of stripes; no flow.', "bc": 'Periodic in both directions; the stirring velocity is zero.'}, "name": "Dye: Diffusion Only",
     "phenomenon": "Vortices & mixing", "preset": {"bands": 6, "stir": 0.0, "diffusion": 4e-4}, "status": "analytical",
     "question": "How fast does diffusion alone smooth the bands?",
     "blurb": "The same bands with the stirring switched off. Each band decays as a pure diffusion problem whose "
              "solution is known.",
     "try": ["Change κ and the number of bands: the decay rate scales as κ·(band wavenumber)²."],
     "observe": "A smooth, exponential decay of the variance.",
     "checks": "Analytical comparison: for stripes with wavenumber m the variance decays as exp(−2κ m² t) "
               "(tested in tests/).",
     "refs": [R["ottino"]]},
    {"method": SP, "exhibit": "Ink in Motion", "key": "mix_stir", "override": {"physics": 'With κ = 0 the dye is a conserved passive scalar: stirring stretches and folds it into finer filaments without changing its variance in exact arithmetic. The decay seen is the numerical diffusion of the bilinear semi-Lagrangian advection once filaments reach the grid scale — a floor of the scheme, reported rather than hidden.', "ic": 'Alternating dye bands in the random stirring flow of the chosen seed.', "bc": 'Periodic in both directions; molecular diffusion switched off.'}, "name": "Dye: Stirring Only",
     "phenomenon": "Vortices & mixing", "preset": {"bands": 6, "diffusion": 0.0}, "status": "numerical",
     "question": "How much variance does the numerical scheme lose without physical diffusion?",
     "blurb": "The same stirring with κ = 0. A conserved dye should keep its variance; the decay seen is numerical "
              "diffusion of the bilinear semi-Lagrangian advection.",
     "try": ["Raise the resolution: the numerical decay slows."],
     "observe": "The variance curve: its decay is entirely numerical.",
     "checks": "Numerical check (a measured floor of the scheme, reported rather than hidden).",
     "refs": [R["ottino"]]},
    # ═════════ pattern formation ═════════
    {"method": RD, "exhibit": "Turing Patterns", "key": "rd_spots", "name": "Spots",
     "phenomenon": "Pattern formation", "preset": {"pattern": "Spots"}, "status": "numerical",
     "question": "Which parameter changes alter the morphology?",
     "blurb": "Two chemicals reacting and diffusing at different rates (the Gray–Scott system) settle from noise "
              "into a field of spots. The resemblance to animal markings is suggestive; it does not establish "
              "a biological mechanism.",
     "try": ["Open the Custom Explorer scene and move F and k in small steps.", "Change the seed (advanced)."],
     "observe": "The pattern coverage saturating as the domain fills.",
     "checks": "Numerical check: the (F, k) values reproduce the morphologies of Pearson's classification; the "
               "explicit scheme clips concentrations to [0, 1] each step (an intervention, reported).",
     "refs": [R["pearson"], R["turing"], R["kondo"]]},
    {"method": RD, "exhibit": "Turing Patterns", "key": "rd_stripes", "name": "Stripes & Coral",
     "phenomenon": "Pattern formation", "preset": {"pattern": "Stripes"}, "status": "numerical",
     "question": "How does the feed/removal balance turn spots into stripes?",
     "blurb": "A different (F, k) pair: spots elongate into branching stripes and coral-like ridges.",
     "try": ["Compare with Spots and Maze."], "observe": "Branching and the steady wavelength.",
     "checks": "Numerical check (Pearson's regimes).", "refs": [R["pearson"]]},
    {"method": RD, "exhibit": "Turing Patterns", "key": "rd_maze", "name": "Labyrinth",
     "phenomenon": "Pattern formation", "preset": {"pattern": "Maze"}, "status": "numerical",
     "question": "What regime freezes into a maze?",
     "blurb": "Stripes that neither close into spots nor straighten, wandering into a labyrinth.",
     "try": ["Move k up or down by 0.002 in the Custom Explorer."], "observe": "The frozen final state.",
     "checks": "Numerical check (Pearson's regimes).", "refs": [R["pearson"]]},
    {"method": RD, "exhibit": "Turing Patterns", "key": "rd_mitosis", "name": "Self-Replicating Spots",
     "phenomenon": "Pattern formation", "preset": {"pattern": "Mitosis"}, "status": "numerical",
     "question": "Which regime makes spots divide?",
     "blurb": "Blobs that grow, stretch and pinch in two — a self-replicating regime of the same equations. The "
              "name recalls cell division; the model contains no biology.",
     "try": ["Lower the feed rate slightly to stop the replication."], "observe": "Division events and saturation.",
     "checks": "Numerical check (Pearson's regimes).", "refs": [R["pearson"], R["kondo"]]},
    {"method": RD, "exhibit": "Turing Patterns", "key": "rd_custom", "name": "Gray–Scott Explorer",
     "phenomenon": "Pattern formation", "preset": {"pattern": "Custom", "F": 0.030, "k": 0.060, "seed": 3}, "status": "numerical",
     "question": "Which (F, k) changes alter the morphology?",
     "blurb": "Set the feed rate F and removal rate k yourself, with a reproducible seed, and map the regimes.",
     "try": ["Sweep k from 0.055 to 0.066 at F = 0.030.", "Sweep F at fixed k."],
     "observe": "Transitions between spots, stripes, mazes and replication.",
     "checks": "Numerical check (reproducible seeds; Pearson's map is the reference).", "refs": [R["pearson"]]},
]

PHENOMENA = ["Wakes & aerodynamics", "Porous media", "Buoyancy & convection", "Shocks & compressible flow",
             "Free surfaces & waves", "Vortices & mixing", "Pattern formation"]

# ───────────────────────── experiments: gallery cards with named presets ─────────────────────────
# Every scene key above belongs to exactly one experiment (checked in tests). Scene keys stay the
# stable identifiers used by saved setups, favourites, recents and clips; an experiment groups the
# presets of one investigation under one card, one question and one representative preview.
EXPERIMENTS = [
    {"id": "cylinder_wake", "name": "Cylinder wake", "question": "How does the wake change with Reynolds number?",
     "presets": [("lbm_cylinder_steady", "Steady wake (Re 40)"), ("lbm_cylinder", "Vortex shedding (Re 180)")],
     "representative": "lbm_cylinder",
     "compare": [("lbm_cylinder_steady", "lbm_cylinder", "Steady versus shedding wake at the same size and speed (matched elapsed convective time).")]},
    {"id": "airfoil_lift", "name": "Airfoil lift", "question": "How do geometry and angle affect circulation, separation and signed lift?",
     "presets": [("lbm_airfoil_neg", "−14°"), ("lbm_airfoil_zero", "0° baseline"), ("lbm_airfoil", "+14°")], "representative": "lbm_airfoil",
     "compare": [("lbm_airfoil_zero", "lbm_airfoil", "Zero-angle baseline versus +14°: circulation-derived lift appears; drag from the wake deficit is approximate."),
                 ("lbm_airfoil_neg", "lbm_airfoil", "Angle reversal at matched conditions: C_l changes sign with similar magnitude.")]},
    {"id": "cycling_drafting", "name": "Cycling and drafting", "question": "How does a second rider change the wake and the drag estimate?",
     "presets": [("lbm_cyclist", "Single rider"), ("lbm_peloton", "Two riders")], "representative": "lbm_peloton",
     "compare": [("lbm_cyclist", "lbm_peloton", "Isolated rider versus two riders at the same speed; the combined wake-deficit drag is an approximation.")]},
    {"id": "flow_text", "name": "Flow around text", "question": "How do gaps and letter shapes redirect the flow?", "presets": [("lbm_name", "Your text")], "representative": "lbm_name"},
    {"id": "car_silhouette", "name": "Car silhouette", "question": "Where does a bluff vehicle shape shed its wake?", "presets": [("lbm_f1", "Car")], "representative": "lbm_f1"},
    {"id": "porous_flow", "name": "Porous flow", "question": "How readily does a grain pack transmit fluid, and why?",
     "presets": [("porous_phi60", "Default sample"), ("porous_connectivity", "Different arrangement"), ("porous_aniso", "Directional flow")],
     "representative": "porous_phi60",
     "compare": [("porous_phi60", "porous_connectivity", "Similar porosity, different arrangement: both measured porosities are shown; k differs by connectivity."),
                 ("porous_phi60", "porous_aniso", "Same sample driven along x and along y: k_x versus k_y (force magnitude held).")]},
    {"id": "tracer_transport", "name": "Tracer through rock", "question": "How does a tracer spread as the flow carries it through a grain pack?",
     "presets": [("tracer_pulse", "Pulse, Pe 20"), ("tracer_diffusive", "Diffusion dominated, Pe 1"), ("tracer_front", "Steady supply")],
     "representative": "tracer_pulse",
     "compare": [("tracer_diffusive", "tracer_pulse", "Diffusion dominated versus carried by the flow: the same rock and flow, Péclet number 1 against 20."),
                 ("tracer_pulse", "tracer_front", "A slug against a steady supply in the same sample: breakthrough curve versus advancing front.")]},
    {"id": "rising_smoke", "name": "Rising smoke", "question": "How does buoyancy turn a smooth column into a turbulent plume?", "presets": [("ns_smoke", "Smoke plume")], "representative": "ns_smoke"},
    {"id": "rayleigh_taylor", "name": "Rayleigh–Taylor instability", "question": "How does the density contrast set the growth of the instability?",
     "presets": [("ns_rt_single", "Single mode"), ("ns_rt", "Multiple modes")], "representative": "ns_rt"},
    {"id": "candle_flame", "name": "Candle flame", "question": "What shapes a laminar diffusion flame and makes its tip flicker?", "presets": [("ns_flame", "Flame model")], "representative": "ns_flame"},
    {"id": "heated_layer", "name": "Heated-layer convection", "question": "When does convection develop, and how does heat transport change?",
     "presets": [("ns_rb_conduction", "Conduction baseline"), ("ns_rb", "Convection cells"), ("ns_rb_vigorous", "Vigorous convection")], "representative": "ns_rb"},
    {"id": "chimney_plume", "name": "Chimney plume", "question": "How does the plume trajectory change with wind speed?",
     "presets": [("ns_chimney_calm", "Calm air"), ("ns_chimney", "Moderate crosswind"), ("ns_chimney_strong", "Strong crosswind")], "representative": "ns_chimney"},
    {"id": "sod_tube", "name": "Sod shock tube", "question": "Where are the shock, the contact and the rarefaction, and how large is the error?", "presets": [("euler_sod", "Sod tube")], "representative": "euler_sod",
     "compare": [("euler_sod", None, "Computed density and velocity against the exact Riemann solution, with mean absolute errors (in the diagnostics).")]},
    {"id": "open_blast", "name": "Open-air blast", "question": "How fast does a blast front expand, and how does it slow down?", "presets": [("euler_blast", "Blast wave")], "representative": "euler_blast"},
    {"id": "blast_obstacles", "name": "Blast and obstacles", "question": "How do boundaries alter shock propagation?",
     "presets": [("euler_city", "Held obstacles"), ("euler_city_erosion", "Experimental erosion")], "representative": "euler_city"},
    {"id": "shock_bubble", "name": "Shock–bubble interaction", "question": "How does the density contrast alter the interface deformation?",
     "presets": [("euler_bubble", "Light bubble"), ("euler_bubble_heavy", "Heavy bubble"), ("euler_twin", "Twin bubbles")], "representative": "euler_bubble"},
    {"id": "still_water", "name": "Still-water baseline", "question": "Does water at rest stay at rest?", "presets": [("sph_rest", "Hydrostatic rest")], "representative": "sph_rest",
     "compare": [("sph_rest", None, "Residual motion and hydrostatic surface before adding waves or moving bodies.")]},
    {"id": "dam_break", "name": "Dam break", "question": "How does the released potential energy drive the surge?", "presets": [("sph_dam", "Dam break")], "representative": "sph_dam"},
    {"id": "blob_impact", "name": "Water-blob impact", "question": "How do impact speed and size change the splash?", "presets": [("sph_drop", "Blob impact")], "representative": "sph_drop"},
    {"id": "sloshing", "name": "Sloshing tank", "question": "How does the response depend on the forcing frequency?", "presets": [("sph_slosh", "Sloshing")], "representative": "sph_slosh"},
    {"id": "pouring", "name": "Pouring", "question": "How does a continuous stream fill a container?", "presets": [("sph_pour", "Pour")], "representative": "sph_pour"},
    {"id": "wave_tank", "name": "Wave tank", "question": "What wavelength, amplitude and reflection does the wavemaker produce?", "presets": [("sph_waves", "Wave train")], "representative": "sph_waves"},
    {"id": "floating_hull", "name": "Floating hull", "question": "Are flotation and motion consistent with the body parameters?",
     "presets": [("sph_ship_still", "Still water"), ("sph_ship", "Waves")], "representative": "sph_ship"},
    {"id": "kelvin_helmholtz", "name": "Kelvin–Helmholtz instability", "question": "How does a shear layer roll up, and how do the billows pair?", "presets": [("spec_kh", "Shear layers")], "representative": "spec_kh"},
    {"id": "decaying_turbulence", "name": "Decaying turbulence", "question": "Why do two-dimensional eddies grow as the flow decays?", "presets": [("spec_decay", "Random field")], "representative": "spec_decay"},
    {"id": "taylor_green", "name": "Taylor–Green vortex", "question": "Does the solver reproduce the exact viscous decay, and does it improve with refinement?", "presets": [("spec_tg", "Taylor–Green")], "representative": "spec_tg",
     "compare": [("spec_tg", None, "Computed kinetic energy against E₀·exp(−4νt) with the relative error (in the diagnostics).")]},
    {"id": "dye_transport", "name": "Dye transport", "question": "How much apparent mixing comes from stirring and how much from diffusion?",
     "presets": [("mix_diffusion", "Diffusion only"), ("mix_stir", "Stirring only"), ("mix_bands", "Stirring with diffusion")], "representative": "mix_bands",
     "compare": [("mix_diffusion", "mix_bands", "Diffusion alone versus stirring with diffusion from the same initial bands."),
                 ("mix_stir", "mix_bands", "Stirring alone (numerical diffusion only) versus stirring with physical diffusion.")]},
    {"id": "gray_scott", "name": "Gray–Scott patterns", "question": "Which parameter changes alter the morphology?",
     "presets": [("rd_spots", "Spots"), ("rd_stripes", "Stripes/coral"), ("rd_maze", "Labyrinth"), ("rd_mitosis", "Replication"), ("rd_custom", "Custom")],
     "representative": "rd_spots"},
]


def experiment_of(key):
    for e in EXPERIMENTS:
        for k, _label in e["presets"]:
            if k == key:
                return e
    return None


def preset_label(key):
    e = experiment_of(key)
    if not e:
        return None
    return dict(e["presets"]).get(key)


def experiments():
    """Experiments with their presets resolved to scene records (gallery cards)."""
    out = []
    for e in EXPERIMENTS:
        presets = []
        for k, label in e["presets"]:
            sc = scene(k)
            if sc:
                presets.append({"key": k, "label": label, "name": sc["name"], "status": sc["status"],
                                "status_label": STATUS_LABEL[sc["status"]], "method": sc["method"]})
        rep = scene(e["representative"]) or scene(e["presets"][0][0])
        out.append({"id": e["id"], "name": e["name"], "question": e["question"], "presets": presets,
                    "representative": e["representative"], "phenomenon": rep["phenomenon"], "method": rep["method"],
                    "methods": sorted({p["method"] for p in presets}), "n_presets": len(presets),
                    "compare": [{"a": a, "b": b, "text": txt} for a, b, txt in e.get("compare", [])]})
    return out


def check_experiments():
    """Every scene maps to exactly one experiment; every experiment preset exists."""
    seen = {}
    problems = []
    for e in EXPERIMENTS:
        for k, _ in e["presets"]:
            if scene(k) is None:
                problems.append(f"experiment {e['id']}: unknown scene {k}")
            if k in seen:
                problems.append(f"scene {k} is in both {seen[k]} and {e['id']}")
            seen[k] = e["id"]
        if scene(e["representative"]) is None or e["representative"] not in dict(e["presets"]):
            problems.append(f"experiment {e['id']}: representative is not one of its presets")
    for s in SCENES:
        if s["key"] not in seen:
            problems.append(f"scene {s['key']} belongs to no experiment")
    return problems
STATUS_LABEL = {"analytical": "Analytical comparison", "numerical": "Numerical check", "qualitative": "Qualitative demonstration"}


def by_method():
    """Ordered {method: [scene, …]} preserving first-seen order."""
    out = {}
    for s in SCENES:
        out.setdefault(s["method"], []).append(s)
    return out


def by_phenomenon():
    out = {p: [] for p in PHENOMENA}
    for s in SCENES:
        out.setdefault(s["phenomenon"], []).append(s)
    return {k: v for k, v in out.items() if v}


def scene(key):
    for s in SCENES:
        if s["key"] == key:
            return s
    return None


def counts():
    """Experiment/preset/method/solver counts generated from the registry (never maintained by hand)."""
    from . import engine
    methods = {s["method"] for s in SCENES}
    return {"experiments": len(EXPERIMENTS), "presets": len(SCENES), "scenes": len(SCENES),
            "methods": len(methods), "solvers": 5, "exhibits": len(engine.EXHIBITS)}


def scene_layers(key):
    """The full layered explanation of a scene, in reading order:
    question → what the colours and motion show → one change to try → what to measure
    (interval, what stays fixed) → physics → equations → actual initial/boundary
    conditions for THIS preset → numerical method, checks and limitations → references.
    Per-scene overrides replace the exhibit's generic text where it would not apply."""
    from . import engine, content
    s = scene(key)
    if not s:
        return None
    ex = s["exhibit"]; m = engine.META.get(ex, {}); d = content.DETAIL.get(ex, {}); setup = content.SETUP.get(ex, {})
    ov = s.get("override", {})
    e = experiment_of(key)
    return {"key": key, "name": s["name"], "exhibit": ex, "method": s["method"], "phenomenon": s["phenomenon"],
            "question": s["question"], "status": s["status"], "status_label": STATUS_LABEL[s["status"]],
            "experiment": e["name"] if e else None, "preset_label": preset_label(key),
            "layers": [
                {"id": "question", "title": "The question", "text": s["question"]},
                {"id": "see", "title": "What the colours and motion show", "text": s["blurb"]},
                {"id": "try", "title": "One change to try", "items": s.get("try", [])[:1]},
                {"id": "observe", "title": "What to measure", "text": s.get("observe", ""),
                 "fixed": _held_fixed(s), "more": s.get("try", [])[1:]},
                {"id": "physics", "title": "Physical explanation", "text": ov.get("physics", d.get("physics", m.get("blurb", "")))},
                {"id": "model", "title": "Equations, symbols and assumptions", "eq": m.get("eq"), "text": d.get("terms", "")},
                {"id": "setup", "title": "Initial and boundary conditions (this preset)", "ic": ov.get("ic", setup.get("ic", "")),
                 "bc": ov.get("bc", setup.get("bc", "")), "preset": s["preset"]},
                {"id": "numerics", "title": "Numerical method, checks and limitations",
                 "text": ov.get("numerics", m.get("numerics", "")), "checks": s.get("checks", m.get("validation", "")),
                 "status": STATUS_LABEL[s["status"]]},
                {"id": "refs", "title": "References", "items": s.get("refs", [])},
            ]}


def _held_fixed(s):
    """What stays fixed while the suggested change is made (from the exhibit's control notes)."""
    from . import engine
    spec = engine.EXHIBITS[s["exhibit"]]["params"]
    fixed = [f"{q.get('label', q['name'])}: {q['fixed']}" for q in spec if q.get("fixed")]
    return fixed
