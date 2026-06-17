"""Exhibit: Rayleigh-Taylor instability (incompressible Navier-Stokes).

Heavy fluid resting on light fluid under gravity: the perturbed interface
rolls up into the characteristic mushroom-cap plumes.

    python demos/rayleigh_taylor.py            # full quality
    python demos/rayleigh_taylor.py --quick    # fast smoke test
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

    nx, ny = (220, 320) if args.quick else (340, 520)
    steps = 1800 if args.quick else 4800
    save_every = 90 if args.quick else 32
    work = ROOT / "results" / "_work_rt"

    subprocess.run([str(SOLVER), "--mode", "rt", "--nx", str(nx), "--ny", str(ny),
                    "--steps", str(steps), "--save_every", str(save_every),
                    "--grav", "1.2e-3", "--conf", "0", "--visc", "1.5e-4",
                    "--iters", "80", "--out", str(work)], check=True)

    n = int([l.split()[1] for l in (work / "meta.txt").read_text().splitlines()
             if l.startswith("nframes")][0])
    skip = max(1, n // 95)
    imgs = [render.field_to_rgb(read_scalar(work, i, nx, ny), render.FLOWZOO_RT,
                                0.0, 1.0, upscale=1)
            for i in range(0, n, skip)]
    render.save_gif(imgs, ROOT / "results" / "rayleigh_taylor.gif", fps=30)
    render.save_mp4(imgs, ROOT / "results" / "rayleigh_taylor.mp4", fps=30)
    print(f"wrote results/rayleigh_taylor.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
