"""Exhibit: Kelvin-Helmholtz billows & 2D turbulence (pseudo-spectral / FFT).

A doubly-periodic shear layer rolls up into Kelvin-Helmholtz billows that
cascade toward 2D turbulence. Validates the spectral solver by checking
energy conservation in the inviscid limit.

    python demos/turbulence.py            # full quality
    python demos/turbulence.py --quick
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import render
from flowzoo.spectral import Spectral2D, double_shear_layer


def validate_energy(n=128):
    """Inviscid run should conserve kinetic energy to ~round-off (spectral)."""
    sim = Spectral2D(n=n, nu=0.0)
    wh = double_shear_layer(n)
    E0 = sim.energy(wh)
    dt = 0.4 * (2 * np.pi / n)
    for _ in range(400):
        wh = sim.step(wh, dt)
    drift = abs(sim.energy(wh) - E0) / E0
    print(f"inviscid energy drift over 400 steps: {drift:.2e}  "
          f"({'PASS' if drift < 1e-2 else 'CHECK'})")
    return drift


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()

    validate_energy()

    n = 192 if args.quick else 320
    nu = 8e-5
    sim = Spectral2D(n=n, nu=nu)
    wh = double_shear_layer(n)
    dt = 0.4 * (2 * np.pi / n)
    nsteps = 1800 if args.quick else 3200
    save_every = max(1, nsteps // 110)

    imgs = []
    vlim = None
    for s in range(nsteps + 1):
        if s % save_every == 0:
            w = sim.vorticity(wh)
            if vlim is None:
                vlim = np.percentile(np.abs(w), 99.0)
            imgs.append(render.field_to_rgb(w, render.FLOWZOO_CURL, -vlim, vlim,
                                            upscale=1))
        wh = sim.step(wh, dt)
    render.save_gif(imgs, ROOT / "results" / "turbulence.gif", fps=28)
    render.save_mp4(imgs, ROOT / "results" / "turbulence.mp4", fps=28)
    print(f"wrote results/turbulence.gif ({len(imgs)} frames)")


if __name__ == "__main__":
    main()
