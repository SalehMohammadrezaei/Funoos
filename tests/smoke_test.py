"""Fast smoke + validation test (no ffmpeg / no GIFs). Run by CI.

Checks that the package imports, the spectral solver conserves energy, and the
compressible solver matches the exact Sod solution.
"""
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import validate
from flowzoo.spectral import Spectral2D, double_shear_layer


def test_spectral_energy_conservation():
    n = 96
    sim = Spectral2D(n=n, nu=0.0)
    wh = double_shear_layer(n)
    e0 = sim.energy(wh)
    dt = 0.4 * (2 * np.pi / n)
    for _ in range(200):
        wh = sim.step(wh, dt)
    drift = abs(sim.energy(wh) - e0) / e0
    assert drift < 1e-2, f"energy drift too large: {drift:.2e}"


def test_sod_shock_tube():
    solver = ROOT / "solvers" / "compressible" / "euler2d"
    subprocess.run(["make", "-C", str(solver.parent)], check=True)
    nx = 300
    work = ROOT / "results" / "_work_smoketest"
    subprocess.run([str(solver), "--mode", "sod", "--nx", str(nx), "--ny", "4",
                    "--tend", str(0.2 * nx), "--steps", "100000",
                    "--save_every", "100000", "--out", str(work)], check=True)
    meta = {l.split()[0]: l.split()[1]
            for l in (work / "meta.txt").read_text().splitlines()}
    rho = np.fromfile(work / "final.bin", dtype=np.float32).reshape(4, nx)[2]
    x = (np.arange(nx) + 0.5) / nx
    exact = validate.exact_sod(x, float(meta["time"]) / nx)
    err = np.mean(np.abs(rho - exact))
    assert err < 0.02, f"Sod mean abs error too large: {err:.4f}"


if __name__ == "__main__":
    test_spectral_energy_conservation(); print("spectral energy: PASS")
    test_sod_shock_tube(); print("sod shock tube: PASS")
