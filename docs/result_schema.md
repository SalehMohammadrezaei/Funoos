# Result schema

Every solve returns an `engine.Result`. Its fields and the metadata the app exports
(`Result.meta()`, saved-experiment files, CSV exports) are defined here.

## `engine.Result`

| field | type | meaning |
|---|---|---|
| `kind` | str | solver family for rendering/diagnostics: `lbm`, `porous`, `ns`, `density`, `particles`, `spectral`, `field`, `quantum` |
| `raw` | list | one entry per saved frame: `[y, x]` scalar array, `(ux, uy)` tuple of `[y, x]` arrays, or an `(N, 3)` particle array `(x, y, |v|)` |
| `times` | list[float] | simulation time of each frame in `hints["time_unit"]`; frame 0 is the initial state, the last frame the final state |
| `info` | str | one-line description shown in the UI |
| `mask` | `[y, x]` uint8 or None | solid cells (1) for grid kinds |
| `hints` | dict | solver metadata (below) |
| `views` | list[str] | render views available for this kind (`Speed`, `Vorticity`, `Streamlines`, `Dye`, `Schlieren`, `Density`, `Particles`, `Foam & spray`, `Speed field`, `Pattern`) |

Arrays follow the public convention **`[y, x]`**, y increasing upward; solvers that
work in `[x, y]` are transposed at the boundary. Large results may be memory-mapped
from a scratch directory (`hints["spilled_to"]`).

### `hints` keys by kind

Common: `time_unit` (str), `dx` (grid spacing in solver units), `steps`, `nu` where defined.

| kind | keys |
|---|---|
| `lbm` | `U` inflow speed, `D` reference length (cells), `tau`, `obstacle`, `probe_x`, `probe_y`, `probe_t`/`probe_uy` (per-step wake probe), `frame_dt_steps` |
| `porous` | `porosity` (the sample actually packed), `porosity_requested` (the target asked for; whole grains can miss it), `permeability` (cells², along `direction`), `mean_ux` (superficial), `mean_ux_pore`, `re_pore` (pore Reynolds number on the grain radius; reading k as a Darcy permeability assumes this stays below one), `k_status` (`settled`/`transient`), `k_change_last10pct`, `force` (per unit mass), `direction`, `grain` (radius in cells), `seed` |
| `tracer` | `peclet` (on the grain **radius**), `dm`, `u_pore`, `u_adv`, `grain`, `axis`, `injection` (`pulse`/`continuous`), `length_cells`, `porosity`, `permeability`, `k_status`, `pore_reynolds`, `flow_settled` (whether the frozen flow had settled), `nu_flow`, `peclet_length_cells`, `pore_volume_cells`, `t_cross`, `steps_requested`, `steps_run`, `truncated`, `crossings_requested`, `crossings_run` (how much of a pore-volume crossing the step budget actually covered), `dt`, `u_max`, `numerical_diffusion`, `div_u_before`/`div_u_max` (before and after the face field is projected divergence-free), plus the series `breakthrough`, `variance_cells2`, `centre_cells`, `mass`, `mass_in`, `mass_out`, `balance` |
| `ns` | `ns_mode` (`smoke`/`rt`/`rb`/`flame`/`wind`), `vel` (list of `(ux, uy)`), `vlim`, `gamma`, `label` (what the scalar is), `kappa` (rb) |
| `density` | `mode` (`sod`/`blast`/`bubble`), `vel`, `nx`, `ny`, `tend`, blast: `p_ambient`, `p0`, `pressure_ratio`, `building`, `structure`, `solid`, `failt`, `debris` |
| `particles` | `Lx`, `Ly`, `dp`, `vmax`, `scene`, `g`, `H`, `a`, `hull` (ship), `c0` (numerical sound speed, set by gravity and fill depth alone), `rho_rms_dev`, `speed_ceiling` (= 1.5·c0), `clamp_events` and `clamp_worst_speed` (how often the speed limiter fired and the fastest motion it removed; a run with `clamp_events` above zero did not carry out the motion that was asked for) |
| `spectral` | `L`, `dt`, `T_end`, `init` |
| `field` | `label` (`dye` or `V concentration`), `kappa`, `stir` (mixing) or `F`, `k`, `Du`, `Dv` (Gray–Scott) |

## `Result.meta()` (JSON)

```json
{"kind": "lbm", "info": "...", "views": ["Vorticity", "Speed", "Streamlines"],
 "frames": 90, "shape": [180, 540], "times": [8800.0, ...], "time_unit": "lattice steps",
 "hints": {"U": 0.08, "D": 23.4, "tau": 0.5056, ...}}
```

Only scalar/str hints are included, plus `quality` and `quality_notes`.

### `quality`

A run can finish, return finite fields and still not be the experiment that was asked
for. `Result.quality` returns `(level, notes)` and both appear in `meta()`:

| level | meaning |
|---|---|
| `quantitative` | nothing the run measured argues against reading its numbers as they stand |
| `qualitative` | the run left a regime its readings assume: the flow had not settled, the pore Reynolds number is above one, the packing missed its porosity target, or the speed limiter rescaled the motion |
| `incomplete` | the step budget stopped the run before the interval it was asked for |

Every note is built from a measurement the run already reported (`truncated`,
`crossings_run`, `flow_settled`, `k_status`, `pore_reynolds`, `porosity_requested`
against `porosity`, `clamp_events`), so the classification states what happened rather
than estimating it. `incomplete` takes precedence over `qualitative` when both apply,
and the notes list every reason regardless.

## Saved experiment (`*.funoos.json`)

Written by *save setup*:

| key | content |
|---|---|
| `app`, `version` | `"Funoos"`, application version |
| `saved` | ISO timestamp |
| `scene`, `exhibit` | scene key (stable id) and exhibit name |
| `params` | the complete resolved parameter set (defaults filled, validated) |
| `advanced` | whether soft limits were relaxed |
| `derived` | derived quantities at save time (ν, Ra, dp, …) |
| `view`, `cmap` | rendering settings |
| `solver_versions` | per solver: source SHA-256 prefix and binary size |
| `result` | `Result.meta()` of the displayed run, when one exists |
| `status` | job state of that run (`completed`, `cancelled`, `failed`) |

Loading validates `params` against the current schema and reports warnings.

## Diagnostics

`postproc.metrics(result)` → `{name: number}`; `postproc.series(result)` → `{name: list}`
with the first key the time axis; `postproc.plots(result)` → `[(title, rgb, explanation)]`.
Metric names are stable identifiers (`strouhal`, `cd_wake_approx`, `cl_circulation`,
`permeability_cells2`, `nusselt`, `mixing_width_final_frac`, `shock_radius_final_cells`,
`sod_err_rho`, `sod_err_u`, `ke_*`, `enstrophy_final`, `pattern_coverage_pct`,
`dye_variance_*`, `particles_final`, `norm_drift`).

Measurements that say how far a result can be trusted are reported the same way, as
numbers rather than prose: `pore_reynolds` and `porosity_requested` (porous and tracer),
`pore_volume_crossings`, `tracer_mass_balance` and `fraction_left_the_sample` (tracer),
and `speed_limiter_events`, `fastest_motion_requested` and `speed_limiter_suppressed_to`
(water). A diagnostic plot repeats them in words when they mean the run is qualitative:
the flow was frozen before it settled, the pore Reynolds number is not creeping, the step
budget stopped short of the crossing asked for, or the packing missed its porosity target.
