"""Profile the computation-to-display pipeline, phase by phase.

    python tools/profile_pipeline.py [--quick] [--cases a,b,c] [--threads 1,2,4,8]

For each representative case it measures, separately:
  solve      solver run (C++ subprocess or Python), including reading its output
  derive     derived fields for the view (speed / vorticity / schlieren / colour limits)
  render     colour mapping + overlays to RGB frames
  encode     MP4 encoding (ffmpeg)
  transfer   base64 data-URL size the UI receives (and the time to build it)
  peak RSS   maximum resident set size of this process after the case (MiB)

The numbers are printed as a Markdown table so they can be pasted into
docs/performance.md. "Before/after" comparisons must be run on the same machine
with the same case list; the script prints the machine summary for that reason.
"""
from __future__ import annotations

import argparse
import base64
import os
import platform
import resource
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CASES = {
    # name: (exhibit, params, view)
    "windtunnel_vort": ("Wind Tunnel", {"resolution": "Low (fast)", "duration": 0.5}, "Vorticity"),
    "windtunnel_stream": ("Wind Tunnel", {"resolution": "Low (fast)", "duration": 0.5}, "Streamlines"),
    "porous": ("Porous Flow", {"resolution": "Low (fast)", "duration": 0.5}, None),
    "smoke": ("Rising Smoke", {"resolution": "Low (fast)", "duration": 0.5}, None),
    "blast": ("Detonation", {"resolution": "Low (fast)", "duration": 0.5}, None),
    "sph_dam": ("The Big Splash", {"duration": 0.5, "particles": 1500}, None),
    "turing": ("Turing Patterns", {"resolution": "Low (fast)", "duration": 0.5}, None),
    "spectral": ("Cloud Billows", {"resolution": "Low (fast)", "duration": 0.5}, None),
}


def _rss_mib():
    ru = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return ru / 1024.0 if sys.platform != "darwin" else ru / (1024.0 * 1024.0)


def profile_case(name, exhibit, params, view):
    from flowzoo import engine, render
    t0 = time.perf_counter()
    res = engine.solve_exhibit(exhibit, params)
    t_solve = time.perf_counter() - t0
    view = view or res.views[0]
    cmap = engine.DEFCMAP[res.kind]
    # derived fields (if the Result caches them, the second render is cheaper)
    t0 = time.perf_counter()
    derive = getattr(res, "derived", None)
    if callable(derive):
        derive(view)
    t_derive = time.perf_counter() - t0
    t0 = time.perf_counter()
    frames = res.render(view, cmap)
    t_render = time.perf_counter() - t0
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "v.mp4"
        t0 = time.perf_counter()
        render.save_mp4(frames, p, fps=26)
        t_encode = time.perf_counter() - t0
        data = p.read_bytes()
    t0 = time.perf_counter()
    b64 = "data:video/mp4;base64," + base64.b64encode(data).decode()
    t_transfer = time.perf_counter() - t0
    h, w = frames[0].shape[:2]
    return {"case": name, "frames": len(frames), "size": f"{w}×{h}",
            "solve": t_solve, "derive": t_derive, "render": t_render, "encode": t_encode,
            "transfer_s": t_transfer, "transfer_MB": len(b64) / 2 ** 20, "rss": _rss_mib()}


def thread_sweep(threads):
    """Wall time of a fixed C++ solve against OMP_NUM_THREADS (the LBM wind tunnel, Low)."""
    from flowzoo import engine
    out = []
    saved = dict(engine._ENV)
    for t in threads:
        engine._ENV["OMP_NUM_THREADS"] = str(t)
        t0 = time.perf_counter()
        engine.solve_exhibit("Wind Tunnel", {"resolution": "Low (fast)", "duration": 0.4})
        out.append((t, time.perf_counter() - t0))
    engine._ENV.clear(); engine._ENV.update(saved)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cases", default=",".join(CASES))
    ap.add_argument("--threads", default="")
    ap.add_argument("--quick", action="store_true")
    a = ap.parse_args()
    print(f"machine: {platform.platform()} · {os.cpu_count()} logical CPUs · python {platform.python_version()}")
    from flowzoo import engine
    print(f"OMP_NUM_THREADS for solvers: {engine._ENV.get('OMP_NUM_THREADS')}\n")
    rows = []
    for name in a.cases.split(","):
        ex, p, v = CASES[name]
        if a.quick:
            p = {**p, "duration": 0.3}
        rows.append(profile_case(name, ex, p, v))
        r = rows[-1]
        print(f"  {name:18s} solve {r['solve']:6.1f}s  derive {r['derive']:5.2f}s  render {r['render']:6.2f}s  "
              f"encode {r['encode']:5.2f}s  transfer {r['transfer_MB']:5.1f} MB  rss {r['rss']:.0f} MiB", flush=True)
    print("\n| case | frames | size | solve s | derive s | render s | encode s | transfer MB | peak RSS MiB |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['case']} | {r['frames']} | {r['size']} | {r['solve']:.1f} | {r['derive']:.2f} | "
              f"{r['render']:.2f} | {r['encode']:.2f} | {r['transfer_MB']:.1f} | {r['rss']:.0f} |")
    if a.threads:
        print("\n| OMP threads | wind-tunnel solve s |\n|---|---|")
        for t, s in thread_sweep([int(x) for x in a.threads.split(",")]):
            print(f"| {t} | {s:.1f} |")


if __name__ == "__main__":
    main()
