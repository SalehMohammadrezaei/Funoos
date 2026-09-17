# Changelog

## Unreleased

Fixes from an external numerical audit of 1.3.1. Each was reproduced first, and each now has a
test that fails without the fix.

* **The tracer outlet no longer feeds the sample.** A few outlet faces run backwards, and the water
  they drew in was given the *injected* concentration, so a steady supply put tracer into the
  downstream end of the sample before any had travelled there. Backflow now draws from the effluent
  region, which is clean. The mass balance could not catch this: the tracer arrived through a
  counted boundary, so the books closed while the result was wrong. Each end is now counted in each
  direction separately, so a breakthrough and a loss back out of the inlet are never the same number.
* **The transport step keeps the update monotone.** The step came from the Courant limit and the
  diffusive limit checked separately, which together can still drain a cell past zero; the negative
  was then clipped away, which creates tracer, since the clip adds back exactly what it removes. One
  combined per-cell limit now sets the step. Round-off clipping is reported (`clipped_mass`);
  anything larger stops the run instead of being hidden.
* **Plume moments weigh tracer, not concentration.** Moments were taken over the pore-averaged
  profile, so a slice holding one pore cell counted as much as a slice holding twenty. On a sample
  with uneven porosity this put the plume in the wrong place: a test case whose centre of mass is at
  3.0 was reported at 2.0.
* **No dispersion coefficient is claimed for a steady supply.** The spreading fit assumes a plume,
  and a steady supply has a growing filled region instead, whose second moment rises with nothing
  dispersing it. Uniform flow through a sample with *no grains*, where mechanical dispersion is
  exactly zero, reported 74,805 times the molecular value, and 15 times the scheme's own numerical
  diffusion, so the plot's own trustworthiness check vouched for it. The steady-supply plot now
  reports the spread without claiming a coefficient, and the pulse text no longer asserts that
  spreading above molecular *is* mechanical dispersion without the numerical-diffusion caveat.
* **An unstable calculation stops instead of returning a video.** Ordinary accepted wind-tunnel
  settings (Low, Re 1200, speed 0.15, size 0.30) produced 87 non-finite frames out of 98 while the
  solver exited successfully and the app rendered them. Every saved state is now checked for a
  finite positive density and a speed below the lattice sound speed, and a run that leaves that
  range stops with exit code 4 and says so, rather than completing.
* **The solver's combined limits are checked before launch.** The relaxation time is built from
  speed, body size and Reynolds number together, so no single control can be bounded to keep it in
  range. Advanced mode accepted settings giving tau 16.7 against a solver limit of 10, which cost
  the user the run. That combination is now refused in both modes, with the reason.
* **An unknown injection is refused.** `transport.run(injection="steady")` silently ran a pulse and
  returned a plausible result for the wrong experiment.
* **Every water frame belongs to one time.** The SPH solver saved a frame before the update and
  another after it, labelling both with the time before, so a dam break returned 55 frames of which
  27 timestamps carried two different states, and the loop ran one update more than asked. The
  initial state is now saved once, each later state is saved at the time it actually reached, and
  the final state is always included.
* **The Gray-Scott frame at time zero is the initial state.** It had already been advanced one step,
  so a blob interior seeded at 0.25 was returned as 0.25625, the run performed one update more than
  requested, and the final state survived only when the step count happened to land on the frame
  interval. The pattern solver now returns frames with the step each was reached at, rather than
  times inferred afterwards from an assumed interval.
* **The tracer no longer claims a settled creeping flow it does not have.** The runner measures the
  pore Reynolds number on the field it actually freezes and records whether the permeability had
  stopped moving. At a driving force of 4 with grain 0.07 and porosity 0.85, every one of them
  inside the recommended range, that is Re 10.8 with the flow still transient, where the docs said
  "far below one" and called freezing it exact. The step budget is reported too: at low Péclet the
  diffusive limit makes the step small and the cap binds, so a run covering 0.28 of the 0.36
  pore-volume crossings asked for now says so rather than presenting a fraction of the experiment
  as the whole of it. Both appear as measurements and as a plain caveat on the breakthrough panel.
* **The spectral solver is actually dealiased now.** The 2/3 mask was applied only to the result of
  the nonlinear term, so modes above the cutoff still multiplied each other and landed inside the
  retained band, where the mask cannot tell that energy from a real interaction between resolved
  modes: a state carrying only |kx| = 25 produced a spurious retained mode at (-14, 1) with
  normalised amplitude 1.6e-05. The state is truncated before any product is formed and stays
  inside the retained band through the step. The same case now leaves 2e-29 there.
* **Held blocks in the compressible solver are walls again.** A face between fluid and a held block
  was solved as an ordinary Riemann problem between two fluids, so mass and energy crossed into the
  block and the reset applied after each stage absorbed the difference without trace: resting fluid
  against a block passed 0.0394 of mass and 0.2705 of energy per unit face. The fluid state is now
  mirrored across such a face, which is the stationary-wall condition and carries no mass and no
  energy, only the pressure the wall pushes back with. Reported minima now cover every step of the
  run and the separately saved final state, where before they scanned only the steps that happened
  to produce a frame and could claim a higher minimum than the final field contains.
* **A pour or a wavemaker faster than the water can carry says so.** The solver rescales any
  particle faster than 1.5·c0, and c0 = 10·√(g·Href) follows from gravity and fill depth alone, so
  an imposed speed never widened that ceiling: a pour asked to run at 3 m/s under low gravity was
  quietly held to 2.12 m/s and still reported as the requested experiment. The setup now warns
  before the run, and the run reports how many times the limiter fired and the fastest motion it
  removed.

## 1.3.1

Boundary conditions for the tracer experiment, reported from use: a steady supply was awkward to
set up, and the outlet did not behave like an outlet.

* **The sample now has a real outlet.** The flow is periodic and the tracer used to travel round
  with it, so what left downstream re-entered upstream and a breakthrough curve read its own
  recycled tracer. The periodic face along the flow is now cut: tracer leaves with the water and
  does not come back, and the water arriving at the inlet carries a prescribed concentration, clean
  after a pulse or the injected value for a steady supply. Both flow directions are handled at the
  cut, so the few faces that run backward drain their cell instead of feeding it.
* **Breakthrough is measured the way a breakthrough curve is defined.** The curve is now the
  flux-averaged concentration over the outlet face, Σuc/Σu, the concentration of the water actually
  leaving. The previous curve was a plain pore average over a slab at the outlet end, which is a
  different quantity; it is still reported beside it.
* **The velocity field is made divergence-free before the tracer moves.** Face velocities averaged
  from the flow solver are only almost divergence-free, and a conservative scheme cannot tell that
  residue from a real source of tracer. A potential is now solved on the pore space by conjugate
  gradients and its gradient subtracted, taking the largest discrete divergence from 3.6e-2 to
  9.7e-15 in the shipped sample, in under two tenths of a second. What is left is reported. The
  tolerance is tight on purpose: the surviving divergence acts as dc/dt = −c ∇·u and compounds over
  a crossing, and at a looser setting a steady supply crept a few parts per million above the
  injected concentration. It now holds that value to twelve digits.
* **A steady supply is now the default.** "Continuous supply" is the default injection, so the
  common setup needs no extra step; the pulse is still one click away.
* **Mass balance is a reported measurement.** Injected minus left minus what is still inside, which
  closes to round-off, with the fraction that has left the sample beside it. These replace the
  earlier drift estimate. The dispersion fit now stops once a fifth of the tracer has left, so the
  fit never runs past the point where the plume is leaving the sample.

## 1.3.0

A new experiment: **Tracer through rock**, the advection and dispersion of a tracer carried by the
flow in the same grain pack the porous experiment uses.

* **What it does.** The pore flow is settled first with the existing lattice-Boltzmann solver, then
  held fixed while a tracer crosses (the pore Reynolds number is far below one, so the field does
  not change meanwhile). Only molecular diffusion is prescribed, from the Péclet number; the
  spreading the plume actually shows comes out of the pore-scale velocities.
* **Controls.** The same rock as porous flow (porosity, grain size, seed, direction, driving
  strength), plus the Péclet number and whether the tracer arrives as a pulse or a steady supply.
  Same porosity, grain size and seed give the same sample, so the two experiments can be compared
  directly.
* **Measurements.** Breakthrough curve at the outlet, arrival time, the spreading coefficient
  fitted from the plume variance, and how many times molecular diffusion that is. The numerical
  diffusion of the advection scheme is reported beside it, and the plot says plainly when the
  measurement is too close to it to mean anything.
* **Three presets.** A pulse at Péclet 20, a diffusion-dominated pulse at Péclet 1, and a steady
  supply at Péclet 50, with guided comparisons between them.
* **Transport scheme.** Finite volume on the flow's own grid: upwind advective fluxes, a five-point
  diffusive flux, and no flux at all through faces touching a grain, so tracer mass is conserved to
  round-off and none enters the solid. The step obeys the Courant and diffusive limits.
* **Checks.** With the flow switched off the plume variance grows as 2·D_m·t to four decimal places;
  tracer mass is conserved to round-off with grains present; a plume carried by the pore flow
  spreads faster than molecular diffusion and faster than the scheme's own numerical diffusion; the
  shipped scene runs and measures (tests/).

The gallery now holds 28 experiments with 51 presets.

## 1.2.1

Pouring never ran: every attempt failed with exit code 2, and the message did not say why.

* **Pouring.** The pour scene fills a real glass 0.13 m wide, but the width of water passed to the
  solver came from the dam-break width control (default 1 m), which is not shown on the pouring
  page. The solver rejects water that cannot fit inside its tank, so every pouring run was refused
  before it started. It now passes the width of the pour stream, from the spout control. Broken
  since the 1.1 series, when each family moved to one shared configuration.
* **Failed runs say what was wrong.** The solvers print the reason they refused a setup; the app
  replaced it with the exit code alone. The reason is now kept and shown, for example "the solver
  rejected this setup: --tau must be in (0.5, 10] (exit code 2)". Exit code 3 reports that the
  solver could not write its output.
* **Checks.** Every scene's settings are compared against the limits its own solver enforces
  (water and fill height inside the tank, particle spacing, relaxation time, lattice speed), and a
  short pouring run must produce frames with water in the glass.

## 1.2.0

A layout review of the real page at eleven window sizes (MacBook Air and Pro defaults, Windows
laptops at 100, 125 and 150 % scaling, 1080p and 1440p monitors) found the Studio crowded and
parts of it outside the window. The interface was restructured and the same measurements are
now a CI job (docs/ui_layout.md).

Studio
* One setup panel: experiment and preset pickers, undo, redo and Advanced on one line; defaults,
  save, load, sweep and saved setups in a More menu. The panel can be hidden to give the field
  the whole width.
* Each control shows one line of help with "more" for the rest; derived quantities are
  collapsed to a one-line summary; Run stays in view.
* The stage has tabs: Field, Plots, Explain and Runs. Plots and the explanation sit beside the
  field on windows 1500 px and wider instead of covering it; run history has labelled actions.
* Readouts under the stage show the run's measurements (lift, drag, Strouhal number,
  permeability, Nusselt number, energy, errors against exact solutions) and the simulated time,
  instead of the frame count, view count and method name.
* Export and zoom moved into one menu; nothing in the stage bar has a fixed minimum width.
  Before, the bar forced 775 px and pushed the readouts and run history out of windows up to
  1366 px wide.
* Column widths and spacing follow the window: 340, 300, 280 and 258 px setup panels, icon tabs
  up to 1366 px, compact spacing up to 780 px of height. The first window fits the screen
  (at most 1440 x 900, at most 92 % x 86 % of the screen); the minimum is 1024 x 640.
* Changing only the resolution or duration no longer relabels a preset as a custom setup.

Measured at the same sizes (tools/check_layout.py):
* controls fully visible without scrolling: 1 to 3 of 7 on laptops before, 4 to 7 now;
* stage area: 41 to 55 % of the window before, 49 to 70 % now; field area 13 to 23 % before,
  18 to 35 % now;
* readouts column outside the window at 1024 to 1366 px before; inside at every size now.

Gallery
* Picture-first cards: 16:10 thumbnails made from the gallery clips without their colour bar,
  wide fields cut to the inflow side, fitted over a blurred copy (tools/make_thumbs.py). One
  metadata line (method, presets, status) replaces the overlapping badges; no separate arrow
  button.
* A card that is not playing shows its poster (a developed frame), never the initial state;
  at most six clips play, the hovered card first.
* Phenomenon chips filter the gallery; a Start here row shows one experiment of each kind of flow.

Detail
* Explanation text used 45 % of its box: the page layout rule also applied to every paragraph.
  It now uses the full width.

Tests and tooling
* tools/check_layout.py (CI job ui-layout): real page, real backend, one real run, eleven sizes;
  fails on horizontal overflow, a wrapped stage toolbar, Run, readouts or transport outside the
  window, too few visible controls, clipped card titles or narrow detail text.
* tests/test_frontend_ui.js: start row, chips and poster-first cards; tabs with arrow keys;
  menus with Escape and outside clicks; the collapsible panel; readout chips; resolution
  keeps the preset name; one-line help.
* tests/test_jobs.py: readouts are measurements; every card has a thumbnail and poster; the first
  window fits the screen.
* tools/record_walkthrough.py records the app walkthrough against the real backend (replaces the
  mock-data recorder); the promo builders use the 27 experiments and write their work files to
  $FUNOOS_PROMO_WORK.

## 1.1.2

Gallery navigation (regression in 1.1.1, fixed)
* Every experiment card failed to open in 1.1.1: the related-experiments rail still read the old catalogue shape (`group.scenes`) after the catalogue moved to experiments, so opening a card threw before the page was shown. The rail now reads experiments, a failure in the optional rail can no longer stop the page from opening, and any other rendering failure is reported instead of leaving the gallery unresponsive.
* Start-up no longer depends on the bridge becoming ready after the script is evaluated: when it is already present, every declaration is initialised before the gallery is built.

Interaction fixes
* Switching experiments while a simulation runs keeps Run disabled and Cancel visible, and both name the experiment that is still simulating.
* Changing the palette during a side-by-side comparison recolours the comparison; the comparison state and the clip on screen stay together.
* A slow reply for an earlier preset can no longer replace the preset chosen later in Studio (request tokens, as in Detail).
* Opening a sweep result or a run from the history loads its complete descriptor from the backend (views, palettes, readouts, metadata, parameters, provenance) and switches to the run's experiment first; new `run_info` API.
* Missing sweep metrics show as "unavailable" instead of 0.00.
* Loading a saved setup clears manual colour limits when the saved limits are automatic and restores the clip frame rate and zoom.
* The simulation-time readout uses the encoded-frame index and, during a comparison, the comparison's own output times.

Tests
* `tests/test_frontend_ui.js` (node + jsdom, in CI and the macOS release build): loads the real page against catalogue and scene replies generated from the Python registry and exercises every card by click, Enter and Space, Back, related-item navigation, preset switching with out-of-order replies, background runs, reopening results, comparison recolouring and clock, sweep metrics and setup loading. It fails on the 1.1.1 page.
* `test_jobs.py`: `run_info` descriptor, expired runs, and scene detection by the most specific preset.

## 1.1.1

Execution and export failures (reproduced, then fixed)
* A completed still-water run could turn "failed": the derived readouts lacked the `rest` case and divided by a zero diffusivity. Readouts are now total over every preset and limiting value and are advisory: a readout problem can no longer change a run's terminal state (tests over all presets).
* Cloud Billows at Ultra with ν = 0.01 produced non-finite fields from frame 10 (ν·k_max²·dt = 2.89 exceeds the explicit-RK4 limit). The spectral solver now integrates the viscous term exactly (integrating-factor RK4); the case reproduced at Low resolution stays finite, and non-finite fields raise a clear error instead of silent NaN frames.
* Sweeps could return NaN metrics, which is not JSON and left the frontend promise hanging: every API reply is now strictly JSON (NaN/inf → null).
* Probe/profile CSV exports sampled a different column from the displayed plot: exports now use the resolved cell and frame captured when the plot was made, and the profile export records the frame and time.
* A 4×4 incompressible grid overflowed the heap (reproduced under AddressSanitizer): the source geometry is bounded and grids below 16 cells are rejected.

Consistency
* One effective configuration per solver family is shared by the runners, the derived readouts, result metadata and reports; the porous force strength and the SPH sound-speed reference now match the solver exactly.
* Porous flow starts at rest (`--U 0`); k is reported as settled or transient from the solver's convergence record; the pore Reynolds number is recorded.
* Frame 0 is the initial state and the final state is always saved for every solver; frame thinning keeps the last frame; warm-up intervals that are dropped are recorded; the frame on screen is identified from the encoded clip position.
* Random initial conditions are drawn on a fixed reference grid so the same seed gives the same continuous field at every resolution (spectral: exact zero-padding/low-pass; Gray–Scott: blob positions as fractions).
* Derived readouts state which quantities change with the resolution setting (grid-unit coefficients, convective time, Rayleigh number); the free-slip plate onset (657.5) replaces the no-slip 1708 where the solver's plates are free-slip.

State and integrity
* Strict numeric parsing ("0,01" → 0.01; "1e", "2abc" rejected); Run is re-enabled when an invalid value is corrected.
* Every asynchronous reply is guarded by its request token and run identity (scene picks, comparisons included).
* Comparison is its own display state; runs must share solver family, view and time unit and are aligned over the shared interval only (nothing repeated beyond a run's duration); probes and exports refer to a single run again after leaving it.
* Sweep children are jobs with immutable parameters and provenance; the run history retains them (duplicate, report, export work); availability is shown.
* Saved setups (schema v2) separate the editable draft from the run's frozen configuration and record whether they match; presentation (view, palette, colour limits) is restored; provenance is frozen when a job starts.

Gallery, readability, rendering, explanations, controls, attribution
* 27 experiment cards with named presets (docs/gallery_map.md); Detail and Studio preset selectors; "Custom setup" label; favourites/recents migrated; counts from the registry.
* Semantic colour tokens with measured contrast (docs/accessibility.md), dark `color-scheme`, every select/option/optgroup styled.
* Streamlines share the full normalisation with the legend; probes use the actual rendered field rectangle; derived caches are counted in the memory budget; encoded clips have a byte budget; single-frame previews derive one frame; disk spill streams frame by frame; gallery videos are released on rebuild, at most six play at once, posters, autoplay/instant-preview settings, reduced motion honoured.
* Explanations resolved per preset in reading order (question first) with initial/boundary conditions for every preset; corrected wording (mixture variable not conserved, wavemaker stroke, held obstacles, shock-radius caveat); missing diagnostics explain themselves; guided comparisons per experiment; window title "Funoos — fluid simulation laboratory".
* Browse and prepare another setup while a run continues (drafts kept per scene; results land in the history); result-vs-controls indicator; Settings (memory, threads, previews, autoplay); inert inactive views, Back button, keyboard-safe favourites and shortcuts.
* Home credit with GitHub link, About page, CITATION.cff, licence credit reconciled, third-party notices packaged, build revision recorded.

Tests and packaging
* Tests now require evidence: mass metadata must exist and be conserved; raw pressure and density minima positive; SPH density deviation < 5 %; frontend logic checked with node; per-preset derived readouts; strict JSON of every reply.
* Native solvers validate arguments; macOS build uses the shared requirements and records resolved versions; gallery generation fails when an MP4 fails; Linux backend detection.

## 1.1.0

Numerics and claims (stage 1, continued)
* Permeability uses the superficial (Darcy) velocity; pore-average velocity stored separately; half-force velocity used everywhere.
* Text geometry uses a bundled font on every platform.
* Spectral runs keep the same simulated interval at every resolution; arrays follow one `[y, x]` convention.
* Rayleigh–Bénard has explicit thermal diffusion; both velocity components are advected with the same frozen field; viscosity scaled by dt.
* Blast pressure is a ratio to ambient (presets migrated); a structure-model choice separates rigid walls from the experimental erosion rule.
* Frame timestamps are actual solver times; the initial and final states are always saved.
* Scientific wording corrected across the scene pages, README and theory notes (candle model, Rayleigh–Taylor approximation, blast wave, hull forces, wave tank, blob impact, Gray–Scott, RK4 conservation, boundary conditions).

Reliability (stage 2)
* Job lifecycle with explicit states, immutable parameter snapshots, Cancel that stops the solver, error envelopes, request tokens, preserved playback state.
* Bounded result store with a memory budget, pinning, LRU eviction, disk spill for large runs, cleanup on cancel/failure/exit and after a crash.

Performance (stage 3)
* Frames streamed to ffmpeg over a raw-video pipe; encoded views cached; instant still previews; one bounded encode worker; vectorised streamline renderer; Euler face-flux arrays (2.3–4× faster, bit-identical); thread setting respected; decorative animation paused. Measurements in docs/performance.md.

Experiments (stage 4)
* Typed parameter schema with units, recommended vs hard limits, dependencies, an advanced mode and derived quantities; validation before any solver starts.
* Named presets, save/load of complete setups with solver provenance, undo/redo, reset, run history with duplicate/pin/compare, parameter sweeps, side-by-side comparison synchronised by simulation time, point probes, line profiles, frame inspection, zoom/pan, CSV export, keyboard operation.

Cases and explanations (stage 5)
* 48 scenes (19 new) organised by phenomenon with a question, a status label and a layered explanation; Sod shock tube, Taylor–Green, still water, single-mode Rayleigh–Taylor, directional permeability, conduction baseline, calm/strong wind, heavy bubble, rigid/eroding buildings, diffusion-only and stirring-only mixing, Gray–Scott explorer, airfoil ±/0°.
* Diagnostics rebuilt: measurements separated from plots; shedding frequency from the per-step wake probe with a confidence rule; signed lift with the aerodynamic convention; wake-deficit drag labelled approximate; normalised mixing width; heat-flux budget with Nusselt number; robust shock-front radius; SPH energies with particle masses; wave gauges and hull motion; absolute values with units.
* Gallery search, method filter, favourites, recent experiments, keyboard-operable cards, studio scene picker and in-studio explanation panel; reduced-motion respected.

Packaging and tests (stage 6)
* Pinned requirements and `pyproject.toml`; build scripts run from their own directory, package only the needed assets, and run a self-test of the packaged app; release checksums; Linux backend and WebView2 hints; legacy `studio.py` marked unsupported.
* Test suites for cases, matrix (solver properties), schema, jobs and media added to CI; a Linux packaging job runs the self-test.
* Native solvers validate their arguments (sizes, non-finite numbers, intervals, unknown modes, truncated masks) and fail with a message before allocating.
* Solver-output readers consolidated in `flowzoo/io.py`; promotional/demo scripts use portable paths.

## 1.0.1
* macOS disk image built on GitHub runners; stage-1 numerical fixes.

## 1.0.0
* First release with the Windows installer.
