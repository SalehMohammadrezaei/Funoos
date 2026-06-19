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


def test_quantum_unitarity():
    """Split-step Schrödinger conserves probability in the closed harmonic well."""
    from flowzoo.quantum import simulate
    prob, phase, V, norm = simulate(n=96, scene="harmonic", steps=240, nframes=20)
    drift = max(abs(x - 1) for x in norm)
    assert drift < 1e-6, f"quantum norm drift too large: {drift:.2e}"


def test_reaction_bounded():
    """Gray–Scott concentrations stay in [0,1] and form structure."""
    from flowzoo.reaction import gray_scott
    fr = gray_scott(n=96, F=0.035, k=0.065, steps=3000, nframes=10, seed=2)
    v = fr[-1]
    assert v.min() >= -1e-6 and v.max() <= 1.0 + 1e-6, "Gray–Scott out of [0,1]"
    assert v.std() > 1e-3, "Gray–Scott formed no structure"


def test_porous_permeability_monotone():
    """Pore-scale LBM permeability rises with porosity (Darcy/Kozeny–Carman trend)."""
    import flowzoo.engine as engine
    k = {}
    for phi in (0.5, 0.72):
        p = {q["name"]: q["default"] for q in engine.EXHIBITS["Porous Flow"]["params"]}
        p.update({"resolution": "Low (fast)", "duration": 0.4, "porosity": phi})
        k[phi] = engine.solve_exhibit("Porous Flow", p).hints["permeability"]
    assert k[0.72] > k[0.5] > 0, f"permeability not monotonic in porosity: {k}"


if __name__ == "__main__":
    test_spectral_energy_conservation(); print("spectral energy: PASS")
    test_sod_shock_tube(); print("sod shock tube: PASS")
    test_quantum_unitarity(); print("quantum unitarity: PASS")
    test_reaction_bounded(); print("reaction-diffusion bounds: PASS")
    test_porous_permeability_monotone(); print("porous permeability: PASS")
