"""Signature exhibit: incident flow shedding vortices off text (LBM).

Renders any string as a solid obstacle and runs the lattice-Boltzmann
external-flow solver, so the flow peels vortices off the letters.

    python demos/flow_around_name.py                 # default: "Funoos"
    python demos/flow_around_name.py --text "Saleh"
    python demos/flow_around_name.py --text "Funoos" --quick
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import geometry, render, io

SOLVER = ROOT / "solvers" / "lbm" / "lbm2d"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--text", default="Funoos")
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    if not SOLVER.exists():
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)

    nx, ny = (560, 220) if args.quick else (1000, 360)
    # characteristic size ~ glyph height; pick viscosity for a lively-but-stable wake
    H = ny * 0.5
    U = 0.08
    Re = 600.0                              # livelier wake -> vortices peel off the letters
    tau = 0.5 + 3.0 * (U * H / Re)
    steps = 7000 if args.quick else 46000
    save_every = 175 if args.quick else 200

    work = ROOT / "results" / "_work_name"
    work.mkdir(parents=True, exist_ok=True)
    mask = geometry.text(nx, ny, args.text, font_frac=0.34, x_frac=0.28,
                         max_w_frac=0.5)
    geometry.save_mask(mask, work / "mask.bin")
    print(f"text='{args.text}'  grid={nx}x{ny}  solid={mask.mean()*100:.1f}%  "
          f"tau={tau:.3f}  steps={steps}")

    subprocess.run([str(SOLVER), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(work / "mask.bin"), "--U", str(U),
                    "--tau", f"{tau:.5f}", "--steps", str(steps),
                    "--save_every", str(save_every), "--out", str(work),
                    "--probe_x", str(int(nx * 0.6)), "--probe_y", str(ny // 2)],
                   check=True)

    meta, frames = io.read_all_frames(work)
    skip = max(1, len(frames) // 90)
    use = frames[len(frames) // 5 :: skip]
    vort = [render.vorticity(ux, uy) for ux, uy in use]
    vmax = np.percentile(np.abs(np.concatenate([v.ravel() for v in vort[-20:]])), 99.0)
    imgs = [render.field_to_rgb(v, render.FLOWZOO_CURL, -vmax, vmax,
                                mask=mask, mask_color=render.SOLID, upscale=1) for v in vort]
    safe = "".join(c if c.isalnum() else "_" for c in args.text).lower()
    out_gif = ROOT / "results" / f"flow_around_{safe}.gif"
    render.save_gif(imgs, out_gif, fps=24)
    render.save_mp4(imgs, ROOT / "results" / f"flow_around_{safe}.mp4", fps=24)
    print(f"wrote {out_gif}")


if __name__ == "__main__":
    main()
