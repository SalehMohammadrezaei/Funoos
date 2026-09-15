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
| `porous` | `porosity`, `permeability` (cells², along `direction`), `mean_ux` (superficial), `mean_ux_pore`, `force` (per unit mass), `direction`, `grain`, `seed` |
| `ns` | `ns_mode` (`smoke`/`rt`/`rb`/`flame`/`wind`), `vel` (list of `(ux, uy)`), `vlim`, `gamma`, `label` (what the scalar is), `kappa` (rb) |
| `density` | `mode` (`sod`/`blast`/`bubble`), `vel`, `nx`, `ny`, `tend`, blast: `p_ambient`, `p0`, `pressure_ratio`, `building`, `structure`, `solid`, `failt`, `debris` |
| `particles` | `Lx`, `Ly`, `dp`, `vmax`, `scene`, `g`, `H`, `a`, `hull` (ship) |
| `spectral` | `L`, `dt`, `T_end`, `init` |
| `field` | `label` (`dye` or `V concentration`), `kappa`, `stir` (mixing) or `F`, `k`, `Du`, `Dv` (Gray–Scott) |

## `Result.meta()` (JSON)

```json
{"kind": "lbm", "info": "...", "views": ["Vorticity", "Speed", "Streamlines"],
 "frames": 90, "shape": [180, 540], "times": [8800.0, ...], "time_unit": "lattice steps",
 "hints": {"U": 0.08, "D": 23.4, "tau": 0.5056, ...}}
```

Only scalar/str hints are included.

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
