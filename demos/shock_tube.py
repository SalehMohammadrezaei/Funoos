"""Validation exhibit: Sod shock tube vs. exact Riemann solution.

Runs the compressible Euler solver on the classic Sod problem and overlays
the simulated density on the exact analytical solution. This is the
quantitative check that the HLLC solver is correct.

    python demos/shock_tube.py
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import validate

SOLVER = ROOT / "solvers" / "compressible" / "euler2d"


def main():
    if not SOLVER.exists():
        subprocess.run(["make", "-C", str(SOLVER.parent)], check=True)
    nx = 600
    t_target = 0.2
    work = ROOT / "results" / "_work_sod"
    subprocess.run([str(SOLVER), "--mode", "sod", "--nx", str(nx), "--ny", "4",
                    "--tend", str(t_target * nx), "--cfl", "0.4",
                    "--steps", "100000", "--save_every", "100000",
                    "--out", str(work)], check=True)

    meta = {l.split()[0]: l.split()[1] for l in (work / "meta.txt").read_text().splitlines()}
    t_phys = float(meta["time"]) / nx
    rho = np.fromfile(work / "final.bin", dtype=np.float32).reshape(4, nx)[2]
    x = (np.arange(nx) + 0.5) / nx
    exact = validate.exact_sod(x, t_phys)

    err = np.mean(np.abs(rho - exact))
    peak_err = abs(rho.max() - exact.max()) / exact.max()
    print(f"t={t_phys:.3f}  mean|err|={err:.4f}  peak density err={peak_err:.2%}")

    plt.rcParams.update({"font.size": 11, "axes.grid": True, "grid.alpha": 0.3})
    fig, ax = plt.subplots(figsize=(8, 4.2))
    ax.plot(x, exact, "-", color="#c0392b", lw=2.2, label="exact Riemann solution")
    ax.plot(x[::6], rho[::6], "o", ms=4, color="#1f3a93", mfc="white",
            label="Funoos HLLC solver")
    ax.set_xlabel("x"); ax.set_ylabel(r"density $\rho$")
    ax.set_title(f"Sod shock tube at t = {t_phys:.2f}  (mean abs error {err:.3f})")
    ax.legend(frameon=False)
    fig.tight_layout()
    out = ROOT / "results" / "shock_tube_validation.png"
    fig.savefig(out, dpi=150)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
