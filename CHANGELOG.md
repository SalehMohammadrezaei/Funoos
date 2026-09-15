# Changelog

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
