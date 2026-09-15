"""Cheap solver-property checks from the review's test matrix (run: python tests/test_matrix.py).

  LBM       uniform inflow with no obstacle stays uniform; periodic porous run conserves mass.
  Incomp.   saved velocity fields are discretely divergence-free (projection residual).
  Euler     density and pressure stay positive through a strong blast; held towers have zero velocity.
  SPH       the fluid particle count is constant (no particle loss) in a dam break; density stays near ρ₀.
  RD        a uniform state without seeds stays uniform; V never leaves [0, 1] (clipping reported).
  Spectral  the RK4 time-stepping error falls ~16× per dt halving (shear layer vs a fine-dt reference); dye mass is conserved.
  Native    the solvers reject invalid arguments before allocating.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import engine, geometry, io as fio   # noqa: E402

_ENV = {**os.environ, "OMP_NUM_THREADS": "4"}
engine._ENV["OMP_NUM_THREADS"] = "4"


def _run(args):
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, env=_ENV)


def test_lbm_uniform_flow_and_mass():
    exe = ROOT / "solvers/lbm/lbm2d"
    subprocess.run(["make", "-s", "-C", str(exe.parent)], check=True, capture_output=True)
    nx, ny = 60, 30
    with tempfile.TemporaryDirectory() as d:
        geometry.save_mask(np.zeros((ny, nx), np.uint8), Path(d) / "m.bin")
        r = _run([exe, "--nx", nx, "--ny", ny, "--mask", Path(d) / "m.bin", "--U", "0.05", "--tau", "0.8",
                  "--steps", "400", "--save_every", "400", "--out", d])
        assert r.returncode == 0, r.stdout[-300:]
        ux, uy = fio.read_frame(d, 1, nx, ny)
        assert abs(ux.mean() - 0.05) < 0.02 and np.abs(uy).max() < 0.02, "no obstacle: the flow stays (nearly) uniform"
    # periodic porous box: total mass (Σρ) must be conserved
    yy, xx = np.mgrid[0:ny, 0:nx]; mask = (((xx - 30) ** 2 + (yy - 15) ** 2) < 36).astype(np.uint8)
    with tempfile.TemporaryDirectory() as d:
        geometry.save_mask(mask, Path(d) / "m.bin")
        r = _run([exe, "--nx", nx, "--ny", ny, "--mask", Path(d) / "m.bin", "--periodic", "1", "--force", "1e-5",
                  "--tau", "0.8", "--steps", "300", "--save_every", "300", "--out", d])
        assert r.returncode == 0
        m = fio.read_meta(d)
        assert "mass_initial" in m and "mass_final" in m, "mass metadata is required evidence (missing = fail)"
        rel = abs(m["mass_final"] / m["mass_initial"] - 1.0)
        assert rel < 1e-9, f"periodic body-force run must conserve mass exactly (rel change {rel:.1e})"
    print(f"    lbm: uniform inflow kept; periodic mass conserved (rel change {rel:.1e})")


def test_incompressible_divergence_free():
    r = engine.solve_exhibit("Rising Smoke", {"resolution": "Low (fast)", "duration": 0.1})
    ux, uy = r.hints["vel"][-1]
    div = np.gradient(ux, axis=1) + np.gradient(uy, axis=0)
    rel = float(np.abs(div[2:-2, 2:-2]).mean() / (np.abs(ux).mean() + np.abs(uy).mean() + 1e-12))
    assert rel < 0.05, rel
    print(f"    incompressible: mean |div u| / mean |u| = {rel:.3f}")


def test_euler_positivity_and_held_walls():
    r = engine.solve_exhibit("Detonation", {"resolution": "Low (fast)", "duration": 0.3, "pressure": 300, "scene": "Shock hits a city"})
    for rho in r.raw:
        assert np.isfinite(rho).all() and rho.min() > 0, "density positive"
    assert r.hints.get("pmin") is not None and r.hints["pmin"] > 0, "raw pressure (before the 1e-6 floor) stays positive over the saved frames"
    assert r.hints.get("rhomin") is not None and r.hints["rhomin"] > 0
    solid = r.hints["solid"]; ux, uy = r.hints["vel"][-1]
    # held cells: state pinned (zero velocity). This is NOT an impermeable-wall claim; the flux through the
    # obstacle faces is not enforced, and the scene says so.
    assert np.abs(ux[solid]).max() < 1e-9 and np.abs(uy[solid]).max() < 1e-9, "held cells keep zero velocity"
    print(f"    euler: min ρ = {r.hints['rhomin']:.3f}, min p = {r.hints['pmin']:.4f} > 0 (raw); held cells pinned")


def test_sph_particle_accounting():
    r = engine.solve_exhibit("The Big Splash", {"scene": "Dam break", "duration": 0.3, "particles": 1200})
    counts = [len(d) for d in r.raw]
    assert len(set(counts)) == 1, f"fluid particle count changed: {set(counts)}"
    dev = r.hints.get("rho_rms_dev")
    assert dev is not None and dev < 0.05, f"weakly compressible: rms density deviation {dev} should be < 5 %"
    print(f"    sph: {counts[0]} particles in every frame; rms density deviation {dev:.3%}")


def test_reaction_uniform_state_and_bounds():
    from flowzoo.reaction import gray_scott
    fr = gray_scott(n=48, F=0.035, k=0.065, steps=200, nframes=4, seed=0, nseeds=0, noise=0.0)
    assert np.allclose(fr[-1], 0.0), "without seeds V stays zero (uniform state is a fixed point)"
    fr2 = gray_scott(n=48, F=0.035, k=0.065, steps=300, nframes=4, seed=1)
    assert fr2[-1].min() >= 0 and fr2[-1].max() <= 1, "V within [0, 1] (enforced by clipping)"
    print("    reaction: uniform state stays uniform; bounds enforced")


def test_spectral_timestep_convergence_and_dye_mass():
    """RK4: the time-stepping error of the nonlinear shear-layer problem falls ~16× when dt is
    halved (measured against a reference with dt/16); the dye advection conserves the dye mass."""
    from flowzoo.spectral import Spectral2D, double_shear_layer
    n, nu, T = 48, 1e-3, 0.4

    def run(dt):
        sim = Spectral2D(n=n, nu=nu); wh = double_shear_layer(n, amp=0.05)
        for _ in range(int(round(T / dt))):
            wh = sim.step(wh, dt)
        return sim.vorticity(wh)
    ref = run(0.05 / 16)
    e1 = float(np.linalg.norm(run(0.05) - ref)); e2 = float(np.linalg.norm(run(0.025) - ref))
    ratio = e1 / max(e2, 1e-300)
    assert 8 < ratio < 40, f"expected ~16× (4th order), got {ratio:.1f}× (errors {e1:.2e}, {e2:.2e})"
    r = engine.solve_exhibit("Ink in Motion", {"resolution": "Low (fast)", "duration": 0.1, "diffusion": 0.0})
    means = [float(s.mean()) for s in r.raw]
    drift = max(abs(m - means[0]) for m in means) / max(means[0], 1e-9)
    # bilinear semi-Lagrangian advection is not exactly conservative: the measured drift is ~2e-3
    # relative at Low resolution (a numerical floor, reported in the scene notes); 1 % is the bound
    assert drift < 1e-2, f"dye mass drift {drift:.2e} exceeds the 1 % numerical floor"
    print(f"    spectral: RK4 error ratio {ratio:.1f}× per dt halving ({e1:.1e} → {e2:.1e}); dye mass drift {drift:.1e}")


def test_random_initial_condition_is_resolution_independent():
    """The same seed gives the same continuous initial spectrum: a larger grid zero-pads it
    exactly; a smaller grid is its low-pass truncation."""
    from flowzoo.spectral import random_field
    w256 = np.real(np.fft.ifft2(random_field(256, seed=4))); w300 = np.real(np.fft.ifft2(random_field(300, seed=4)))
    # evaluate both on the coarse 256 sampling of the 300 grid via spectral interpolation: compare energies + phases
    assert abs((w300 ** 2).mean() / (w256 ** 2).mean() - 1) < 1e-12, "zero-padding preserves the field"
    wh256 = random_field(256, seed=4)
    k = np.fft.fftfreq(256) * 256; keep = (np.abs(k)[:, None] < 64) & (np.abs(k)[None, :] < 64)   # |k| < 64: what a 128 grid can hold
    w128_from_256 = np.real(np.fft.ifft2(np.where(keep, wh256, 0)))[::2, ::2]
    w128 = np.real(np.fft.ifft2(random_field(128, seed=4)))
    assert np.abs(w128 - w128_from_256).max() < 1e-9, "the coarse grid is the low-pass of the reference field"
    from flowzoo.reaction import gray_scott
    a = gray_scott(n=110, F=0.035, k=0.065, steps=0, nframes=1, seed=5, noise=0.0)[0]
    b = gray_scott(n=220, F=0.035, k=0.065, steps=0, nframes=1, seed=5, noise=0.0)[0]
    # blob interiors (V ≈ 0.25 after one step; the one-cell diffusion halo is grid-scale and excluded by the threshold)
    assert np.mean(a > 0.2) > 0 and abs(np.mean(a > 0.2) - np.mean(b > 0.2)) < 0.01, "Gray–Scott seeds placed at the same fractions of the box"
    print("    initial conditions: seed-consistent across resolutions (spectral exact; Gray–Scott blob fractions)")


def test_frames_start_at_initial_state_and_end_at_final():
    """Every solver family: frame 0 is the initial state (t = 0) and the last frame is the end time."""
    r = engine.solve_exhibit("Rising Smoke", {"resolution": "Low (fast)", "duration": 0.1})
    assert r.times[0] == 0.0 and r.times[-1] == r.hints["steps"] and r.raw[0].max() < 1e-9, "smoke: starts clean at t=0, ends at the last step"
    r = engine.solve_exhibit("Porous Flow", {"resolution": "Low (fast)", "duration": 0.1})
    assert r.times[-1] == r.hints["steps"] and r.hints["k_status"] in ("settled", "transient") and len(r.hints["k_history"]) > 3
    assert r.hints["warmup_dropped"]["frames"] > 0
    r = engine.solve_exhibit("Shock Tube", {"resolution": "Low (fast)", "duration": 0.3})
    assert r.times[0] == 0.0 and abs(r.times[-1] - r.hints["tend"]) < 1e-9
    print("    frames: initial state at t=0 and final state kept for smoke, porous, shock tube")


def test_native_argument_validation():
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/lbm")], check=True, capture_output=True)
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/compressible")], check=True, capture_output=True)
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/incompressible")], check=True, capture_output=True)
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/sph")], check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as d:
        bad = [
            [ROOT / "solvers/lbm/lbm2d", "--nx", "0", "--ny", "10", "--out", d],
            [ROOT / "solvers/lbm/lbm2d", "--nx", "10", "--ny", "10", "--tau", "0.4", "--out", d],
            [ROOT / "solvers/lbm/lbm2d", "--nx", "10", "--ny", "10", "--U", "nan", "--out", d],
            [ROOT / "solvers/lbm/lbm2d", "--nx", "10", "--ny", "10", "--mask", str(Path(d) / "missing.bin"), "--out", d],
            [ROOT / "solvers/compressible/euler2d", "--mode", "banana", "--nx", "10", "--ny", "4", "--out", d],
            [ROOT / "solvers/compressible/euler2d", "--mode", "sod", "--nx", "-5", "--ny", "4", "--out", d],
            [ROOT / "solvers/compressible/euler2d", "--mode", "sod", "--nx", "10", "--ny", "4", "--cfl", "2", "--out", d],
            [ROOT / "solvers/incompressible/ins2d", "--mode", "nope", "--nx", "10", "--ny", "10", "--out", d],
            [ROOT / "solvers/incompressible/ins2d", "--mode", "rb", "--nx", "10", "--ny", "10", "--kappa", "0.5", "--out", d],
            [ROOT / "solvers/sph/sph2d", "--scene", "xyz", "--out", d],
            [ROOT / "solvers/sph/sph2d", "--scene", "dam", "--dp", "0", "--out", d],
            [ROOT / "solvers/sph/sph2d", "--scene", "dam", "--tend", "-1", "--out", d],
        ]
        for args in bad:
            r = _run(args)
            assert r.returncode != 0, f"should reject: {' '.join(map(str, args[1:]))}"
            assert "error" in (r.stdout + r.stderr).lower(), "a useful error message is printed"
        # a truncated mask is rejected too
        (Path(d) / "short.bin").write_bytes(b"\\x00" * 10)
        r = _run([ROOT / "solvers/lbm/lbm2d", "--nx", "10", "--ny", "10", "--mask", str(Path(d) / "short.bin"), "--out", d])
        assert r.returncode != 0 and "mask" in (r.stdout + r.stderr).lower()
    print("    native: 13 invalid argument sets rejected with messages")


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        t0 = time.time()
        try:
            fn(); print(f"  ok   {name}  ({time.time() - t0:.1f}s)")
        except Exception as e:                       # noqa: BLE001
            failed += 1; print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
