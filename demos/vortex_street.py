"""Exhibit: Karman vortex street behind a circular cylinder (LBM).

Runs the C++ LBM solver, renders a cinematic vorticity animation, and
validates the shedding frequency against the expected Strouhal number
(St ~ 0.2 for Re ~ 100-200).

    python demos/vortex_street.py            # full quality
    python demos/vortex_street.py --quick    # fast smoke test
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


def ensure_solver():
    if not SOLVER.exists():
        print("building LBM solver...")
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)


def strouhal(out_dir, D, U, drop_frac=0.5):
    """Estimate St = f*D/U from the wake transverse-velocity probe."""
    data = np.loadtxt(out_dir / "probe.csv", delimiter=",", skiprows=1)
    step, uy = data[:, 0], data[:, 1]
    n0 = int(len(uy) * drop_frac)          # drop the start-up transient
    sig = uy[n0:] - uy[n0:].mean()
    if np.allclose(sig, 0):
        return float("nan")
    freqs = np.fft.rfftfreq(len(sig), d=1.0)   # cycles per step
    amp = np.abs(np.fft.rfft(sig))
    f = freqs[1 + np.argmax(amp[1:])]
    return f * D / U


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    ensure_solver()

    nx, ny = (480, 180) if args.quick else (820, 260)
    D = 24 if args.quick else 34
    cx, cy = nx // 4, ny // 2 + 2          # slight offset breaks symmetry -> sheds
    U = 0.08
    Re = 160.0
    nu = U * D / Re
    tau = 0.5 + 3.0 * nu
    steps = 6000 if args.quick else 42000
    save_every = 150 if args.quick else 200

    work = ROOT / "results" / "_work_vortex"
    mask = geometry.cylinder(nx, ny, cx, cy, D / 2)
    work.mkdir(parents=True, exist_ok=True)
    mask_path = work / "mask.bin"
    geometry.save_mask(mask, mask_path)

    print(f"Re={Re:.0f}  D={D}  U={U}  tau={tau:.4f}  grid={nx}x{ny}  steps={steps}")
    subprocess.run([str(SOLVER), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(mask_path), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(save_every),
                    "--out", str(work), "--probe_x", str(cx + 3 * D),
                    "--probe_y", str(ny // 2)], check=True)

    # --- render ---
    meta, frames = io.read_all_frames(work)
    skip = max(1, len(frames) // 130)          # ~130 frames into the GIF
    use = frames[len(frames) // 5 :: skip]     # drop first 20% (transient)
    vort = [render.vorticity(ux, uy) for ux, uy in use]
    vmax = np.percentile(np.abs(np.concatenate([v.ravel() for v in vort[-20:]])), 99.5)
    imgs = [render.field_to_rgb(v, render.FLOWZOO_CURL, -vmax, vmax,
                                mask=mask, upscale=2) for v in vort]
    out_gif = ROOT / "results" / "vortex_street.gif"
    render.save_gif(imgs, out_gif, fps=24)
    render.save_mp4(imgs, ROOT / "results" / "vortex_street.mp4", fps=24)

    # --- validate ---
    St = strouhal(work, D, U)
    print(f"\nValidation: Strouhal St = {St:.3f}  (expected ~0.15-0.21 at Re~160)")
    ok = 0.13 <= St <= 0.24
    print(f"  -> {'PASS' if ok else 'CHECK'}")
    print(f"wrote {out_gif}")


if __name__ == "__main__":
    main()
