# Testing

All suites run on every push (`.github/workflows/ci.yml`) after building the four
C++ solvers; the macOS release workflow runs them again with the freshly built
binaries and then runs the packaged app's self-test. Each suite is a plain script
(`python tests/<suite>.py`) that prints measured values next to its verdict.

| suite | area | what it establishes |
|---|---|---|
| `smoke_test.py` | spectral, Euler, RD, porous, quantum | spectral energy drift < 1e-7 with ν = 0 (measured 2e-9); Sod mean density error < 0.01 (measured 0.003); Gray–Scott bounded (clipping is enforced — see note); permeability rises with porosity; quantum norm |
| `test_numerics.py` | LBM, thermal, coordinates, time, geometry | plane-Poiseuille permeability (analytical, 0.07 %); RB diffusion with buoyancy off; asymmetric-field orientation/vorticity/derivatives; resolution-independent end time; font fallback; dye orientation |
| `test_cases.py` | scene claims | Sod density + velocity errors and convergence; Taylor–Green analytical decay; diffusion-only dye vs exp(−2κm²t); conduction baseline Nu = 1; porous k_x ≫ k_y, Darcy linearity, disconnected sample; SPH still water; airfoil lift sign mirror; registry completeness |
| `test_matrix.py` | solver properties | LBM uniform inflow; incompressible divergence residual (0.3 %); Euler positivity and held walls; SPH particle accounting; Gray–Scott uniform state and bounds; RK4 error ratio 16× per dt halving; dye mass conservation; native argument validation (13 invalid argument sets rejected with messages, truncated masks refused) |
| `test_schema.py` | parameter schema | every shipped preset valid; invalid values (NaN, strings, out of solver limits, unknown names) fail before execution; hidden controls ignored; integers coerced; recommended ranges need advanced mode; active controls change derived quantities; blast pressure ratio migration |
| `test_jobs.py` | frontend/backend contract, resource use | cancellation kills the solver; job states and immutable snapshots; error envelopes; request tokens and superseded encodes; view cache; previews; store bounds, pinning, disk spill and cleanup; sweeps; comparison; probes/profiles; project save/load; temp sweep after a crash |
| `test_media.py` | media/export, colour mapping | streamed MP4/GIF encode → decode with the right frame count and size; generator input; field/legend agreement incl. gamma and floor; palette independence; empty vs zero; derived-field cache; actual frame times; estimate |
| `test_frontend.js` (node) | frontend logic | complete numeric parsing, Run re-enabled after a corrected value, hard vs recommended limits, stale-response tokens, encoded-frame index, favourite/recent migration, result-vs-controls identity |
| `test_frontend_ui.js` (node + jsdom) | gallery and Studio interaction | loads the real `index.html`, `web/logic.js` and `web/app.js` against the catalogue and scene responses generated from the Python registry: every experiment card opens by click, Enter and Space, with its layers, preset selector and related experiments; Back; related-item navigation; out-of-order preset replies in Detail and Studio; Run/Cancel state when switching experiments during a run; reopening a background result from the history (switches to its experiment); comparison clock and recolouring; "unavailable" sweep metrics; setup load restoring automatic limits, fps and zoom |
| `tools/check_layout.py` (Playwright + Chromium, CI job `ui-layout`) | layout at real window sizes | the real page and backend, one real run, then eleven window sizes from 1024×640 to 2560×1361 (MacBook Air/Pro defaults, Windows laptops at 100/125/150 %, 1080p and 1440p monitors): no horizontal overflow or column pushed out of the window, a single-row stage toolbar, Run, readouts and transport inside the window, a minimum number of controls visible without scrolling, detail text using its box, gallery titles not clipped; screenshots uploaded as a CI artifact (docs/ui_layout.md) |
| `Funoos --selftest` | packaging | bundled solvers, font and encoder work inside the packaged app (CI on Linux; build scripts on Windows/macOS) |

The pure frontend logic lives in `web/logic.js` and is checked with node
(`tests/test_frontend.js`, run in CI). The interaction test (`tests/test_frontend_ui.js`,
run in CI after `npm install --no-save jsdom@24`) drives the real page with a stubbed
bridge whose catalogue and scene replies come from the Python registry, so a change of
the catalogue shape that the page does not follow fails in CI. What jsdom cannot show
(native dropdown rendering, actual video decoding and playback, layout) is covered by
manual walkthrough only.

## Tolerances

Tolerances come from the analytical behaviour or a convergence study, not from
the first passing value: e.g. the Sod error bound is twice the measured value at the
lowest resolution used in the app, the Taylor–Green bound (1e-6) is far above the
measured 1e-15 to stay robust across BLAS/FFT builds, and the diffusion-only dye
bound (3 %) accounts for the higher harmonics of the square-wave stripes.

## Numerical interventions that are reported, not hidden

* Gray–Scott clips concentrations to [0, 1] each step.
* The SPH solver limits particle speed to 1.5 c₀ and floors the wall density at ρ₀.
* The Euler solver floors pressure and density at 1e-6 in the reconstruction.
* The LBM wind tunnel uses an outlet relaxation sponge over the last 12 %.

Each is stated in the scene notes or `docs/theory.md`.
