"""Exhibit: shock-bubble interaction (compressible Euler).

A planar shock sweeps across a light-gas bubble; the density mismatch
baroclinically rolls the bubble into a vortex pair -- a classic Richtmyer-
Meshkov-style mixing problem, shown in schlieren.

    python demos/shock_bubble.py            # full quality
    python demos/shock_bubble.py --quick
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

SOLVER = ROOT / "solvers" / "compressible" / "euler2d"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    if not SOLVER.exists():
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)

    nx, ny = (300, 150) if args.quick else (640, 320)
    tend = 80 if args.quick else 230
    save_every = 6 if args.quick else 18
    work = ROOT / "results" / "_work_bubble"
    subprocess.run([str(SOLVER), "--mode", "bubble", "--nx", str(nx), "--ny", str(ny),
                    "--tend", str(tend), "--cfl", "0.4", "--steps", "200000",
                    "--save_every", str(save_every), "--out", str(work)], check=True)

    meta = {l.split()[0]: l.split()[1] for l in (work / "meta.txt").read_text().splitlines()}
    n = int(meta["nframes"]); skip = max(1, n // 110)
    imgs = []
    for i in range(0, n, skip):
        rho = np.fromfile(work / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx)
        sch = render.schlieren(rho)
        imgs.append(render.field_to_rgb(sch, render.FLOWZOO_EMBER, 0.0,
                                        np.percentile(sch, 99.5) + 1e-6,
                                        upscale=1, gamma=0.7))
    render.save_gif(imgs, ROOT / "results" / "shock_bubble.gif", fps=26)
    render.save_mp4(imgs, ROOT / "results" / "shock_bubble.mp4", fps=26)
    print(f"wrote results/shock_bubble.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
