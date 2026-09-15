# Changelog

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
