# Changelog

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
