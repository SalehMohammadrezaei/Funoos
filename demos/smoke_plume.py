"""Exhibit: rising buoyant smoke plume (incompressible Navier-Stokes).

A hot, dyed source at the floor; Boussinesq buoyancy lifts it into a swirling
plume, with vorticity confinement keeping the small-scale curls crisp.

    python demos/smoke_plume.py            # full quality
    python demos/smoke_plume.py --quick    # fast smoke test
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import render

SOLVER = ROOT / "solvers" / "incompressible" / "ins2d"


def read_scalar(out_dir, i, nx, ny):
    return np.fromfile(Path(out_dir) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    if not SOLVER.exists():
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)

    nx, ny = (180, 280) if args.quick else (300, 460)
    steps = 1500 if args.quick else 5200
    save_every = 60 if args.quick else 26
    work = ROOT / "results" / "_work_smoke"

    subprocess.run([str(SOLVER), "--mode", "smoke", "--nx", str(nx), "--ny", str(ny),
                    "--steps", str(steps), "--save_every", str(save_every),
                    "--buoy", "2.5e-3", "--conf", "8", "--visc", "8e-5",
                    "--out", str(work)], check=True)

    n = int([l.split()[1] for l in (work / "meta.txt").read_text().splitlines()
             if l.startswith("nframes")][0])
    skip = max(1, n // 95)                # keep the GIF lean (~100 frames)
    imgs = [render.field_to_rgb(read_scalar(work, i, nx, ny), render.FLOWZOO_EMBER,
                                0.0, 0.85, upscale=1, gamma=0.85)
            for i in range(0, n, skip)]
    render.save_gif(imgs, ROOT / "results" / "smoke_plume.gif", fps=30)
    render.save_mp4(imgs, ROOT / "results" / "smoke_plume.mp4", fps=30)
    print(f"wrote results/smoke_plume.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
