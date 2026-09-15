# Performance: the computation-to-display pipeline

Measured with `python tools/profile_pipeline.py` (same machine, same cases, same
simulated interval and output quality before and after). All times are wall-clock
seconds; "transfer" is the size of the base64 data URL the UI receives; peak RSS is
the profiler process after the case.

Machine: Linux (WSL2), 192 logical CPUs (solvers pinned to 8 OpenMP threads), Python 3.12,
ffmpeg 6.1. Cases use the *Low (fast)* resolution and duration 0.5 so the whole table
runs in a few minutes; the ratios are what matters.

## Before (v1.0.1)

| case | frames | size | solve s | render s | encode s | transfer MB | peak RSS MiB |
|---|---|---|---|---|---|---|---|
| windtunnel_vort | 97 | 644×180 | 4.9 | 0.43 | 0.66 | 0.1 | 196 |
| windtunnel_stream | 97 | 644×180 | 5.7 | **15.27** | 0.84 | 1.3 | 284 |
| porous | 81 | 332×216 | 1.5 | 0.21 | 0.42 | 0.0 | 284 |
| smoke | 115 | 272×264 | 5.4 | 0.28 | 0.58 | 0.2 | 284 |
| blast | 29 | 356×252 | 0.8 | 0.09 | 0.14 | 0.1 | 284 |
| sph_dam | 121 | 816×450 | 1.5 | 1.15 | 1.13 | 0.3 | 284 |
| turing | 113 | 368×264 | 1.2 | 0.31 | 0.66 | 0.4 | 284 |
| spectral | 94 | 257×153 | 4.0 | 0.15 | 0.36 | 0.1 | 284 |

## After (this release)

| case | frames | size | solve s | derive s | render s | encode s | transfer MB | peak RSS MiB |
|---|---|---|---|---|---|---|---|---|
| windtunnel_vort | 97 | 644×180 | 6.5 | 0.03 | 0.45 | **0.12** | 0.1 | 199 |
| windtunnel_stream | 97 | 1252×360 | 4.3 | 0.01 | **4.32** | 0.37 | 3.0 | 312 |
| porous | 81 | 332×216 | 1.3 | 0.00 | 0.21 | **0.05** | 0.0 | 312 |
| smoke | 115 | 272×264 | 5.4 | 0.00 | 0.28 | **0.08** | 0.2 | 312 |
| blast | 30 | 356×252 | **0.6** | 0.00 | 0.10 | 0.06 | 0.1 | 312 |
| sph_dam | 122 | 816×450 | 0.5 | 0.00 | 1.36 | **0.32** | 0.3 | 312 |
| turing | 113 | 368×264 | 1.2 | 0.00 | 0.29 | **0.11** | 0.4 | 312 |
| spectral | 94 | 257×153 | 3.8 | 0.01 | 0.21 | **0.07** | 0.1 | 312 |

Solve times vary by ±30 % between runs on this shared machine; treat differences
there as noise except for the compressible solver (below).

## What changed and what it bought

| change | effect (measured) |
|---|---|
| Frames are streamed to ffmpeg as raw video over a pipe (no PNG directory); a generator feeds the encoder one frame at a time | encode 5–10× faster (0.66 → 0.12 s wind tunnel, 1.13 → 0.32 s SPH); no frame list is materialised for the clip |
| Streamlines: vectorised numpy integrator + rasteriser with streamplot-style occupancy control, instead of one matplotlib figure per frame | 15.3 → 4.3 s for 97 frames **at 2× the output resolution** (per frame at equal size: 0.30 → 0.05 s, 6.5×) |
| Derived fields (speed, vorticity, schlieren, colour limits) cached per view on the result | a palette change no longer recomputes them (derive column ≈ 0) |
| Encoded clips cached per (run, view, palette, fps, limits) | switching back to a palette or view already seen is instant (served from cache; see `tests/test_jobs.py::test_view_cache_preview_and_superseded`) |
| Instant still preview: a palette change first re-maps the frame on screen as one PNG, the clip follows; a run shows its final frame before the clip is encoded | first useful output appears before any encoding |
| Bounded encode worker + request tokens: one encode at a time, and a request superseded by a newer one for the same run is abandoned before or during encoding | no wasted encodes when the user flips palettes quickly |
| Euler residual rewritten with face-flux arrays (no OpenMP atomics), then cell-wise accumulation | Sod 300×4: 0.13 → 0.03 s; blast 300×300: 1.79 → 0.79 s (2.3×); results bit-identical (`max|Δρ| = 0`) |
| Matplotlib figures reused (particles), guarded by a per-frame lock instead of a lock around the whole clip | cancellation and other requests are never blocked for a whole encode |
| Thread policy: a user-set `OMP_NUM_THREADS` is respected; otherwise min(8, cores) | see sweep below |
| Decorative work paused: the hero canvas stops when not on the home page, during a run, when the window is hidden, and under reduced-motion; hidden gallery clips are paused | less CPU/GPU spent while a simulation runs |
| Large results (> `FUNOOS_DISK_SPILL_MB`, default 256 MB) are memory-mapped from a scratch directory that is removed on eviction and swept after a crash | repeated large runs do not grow RAM; a disk budget (`FUNOOS_DISK_MB`) bounds the spill |
| Resource estimate before a run (grid, frames, memory, rough time) shown under the Run button | the user knows what "Ultra × 3" costs before starting |

## OpenMP thread sweep (LBM wind tunnel, Low, duration 0.4)

| OMP threads | solve s |
|---|---|
| 1 | 22.3 |
| 2 | 11.3 |
| 4 | 6.2 |
| 8 | 4.0 |
| 16 | 3.0 |

Scaling is close to linear to 8 threads and flattens after; the default stays at
min(8, cores) so a shared machine is not oversubscribed. Set `OMP_NUM_THREADS` to
override.

## Not done (and why)

* **Local media URLs instead of base64.** pywebview's built-in HTTP server serves
  the app directory, which is read-only inside a packaged app, so clips still travel
  as data URLs. A writable media directory served by the app is a follow-up.
* **SPH/pressure-solver native optimisation.** Profiling shows the solve is not the
  bottleneck at Low/Medium; the Euler atomics were the one clear win and were done.
