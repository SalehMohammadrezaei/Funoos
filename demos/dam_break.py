"""Exhibit: dam break splash (smoothed-particle hydrodynamics).

A water column collapses and surges across a tank. Validates the leading-edge
surge speed against dry-bed dam-break theory (front speed -> 2*sqrt(g*H)).

    python demos/dam_break.py            # full quality
    python demos/dam_break.py --quick
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import render

SOLVER = ROOT / "solvers" / "sph" / "sph2d"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    if not SOLVER.exists():
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)

    dp = 0.045 if args.quick else 0.025
    a, H, Lx, Ly = 1.0, 2.0, 5.0, 3.2
    work = ROOT / "results" / "_work_sph"
    subprocess.run([str(SOLVER), "--a", str(a), "--H", str(H), "--Lx", str(Lx),
                    "--Ly", str(Ly), "--dp", str(dp), "--tend", "1.6",
                    "--save_every", "30" if args.quick else "60", "--out", str(work)],
                   check=True)

    meta = {l.split()[0]: l.split()[1] for l in (work / "meta.txt").read_text().splitlines()}
    n = int(meta["nframes"]); g = float(meta["g"])
    skip = max(1, n // 110)
    vmax = 1.2 * np.sqrt(2 * g * H)
    cmap = render.FLOWZOO_WATER

    imgs = []
    ms = 9 if args.quick else 6
    for i in range(0, n, skip):
        d = np.fromfile(work / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3)
        fig = plt.figure(figsize=(6.4, 6.4 * Ly / Lx), dpi=110)
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(render.INK)
        fig.patch.set_facecolor(render.INK)
        ax.scatter(d[:, 0], d[:, 1], c=np.clip(d[:, 2] / vmax, 0, 1), cmap=cmap,
                   s=ms, edgecolors="none")
        ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
        fig.canvas.draw()
        w, h = fig.canvas.get_width_height()
        buf = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h, w, 4)
        imgs.append(buf[..., :3].copy())
        plt.close(fig)
    render.save_gif(imgs, ROOT / "results" / "dam_break.gif", fps=28)
    render.save_mp4(imgs, ROOT / "results" / "dam_break.mp4", fps=28)

    # --- validation: early surge-front speed vs 2*sqrt(g*H) ---
    fr = np.loadtxt(work / "front.csv", delimiter=",", skiprows=1)
    t, xf = fr[:, 0], fr[:, 1]
    mask = (xf > a) & (xf < 0.8 * Lx)        # after release, before far wall
    if mask.sum() > 3:
        speed = np.polyfit(t[mask], xf[mask], 1)[0]
        theory = 2 * np.sqrt(g * H)
        print(f"surge-front speed = {speed:.2f} m/s   theory 2*sqrt(gH) = {theory:.2f}   "
              f"ratio {speed/theory:.2f}")
    print(f"wrote results/dam_break.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
