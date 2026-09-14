"""Regression tests for the numerical fixes (run with: python tests/test_numerics.py).

Each test pins a fix to an analytical or self-consistency check so the bug cannot
silently return.
"""
import subprocess, sys, tempfile
from pathlib import Path
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


import os
_ENV = {**os.environ, "OMP_NUM_THREADS": "4"}   # the app pins threads too; 192 on a tiny grid crawls


def _run(args):
    subprocess.run([str(a) for a in args], check=True, capture_output=True, env=_ENV)


def _meta(d):
    out = {}
    for line in (Path(d) / "meta.txt").read_text().splitlines():
        k = line.split()
        if len(k) == 2:
            try: out[k[0]] = float(k[1])
            except ValueError: pass
    return out


def test_permeability_poiseuille():
    """Plane-Poiseuille channel: superficial Darcy permeability k = gap^3/(12*Ny) cells^2
    (halfway bounce-back => effective aperture = gap). Catches the pore-average /
    superficial mix-up (a 1/phi error) and the missing half-force term."""
    from flowzoo import geometry
    exe = ROOT / "solvers" / "lbm" / "lbm2d"
    subprocess.run(["make", "-C", str(exe.parent)], check=True, capture_output=True)
    nx, ny, gap = 16, 40, 20
    mask = np.ones((ny, nx), dtype=np.uint8); lo = (ny - gap) // 2
    mask[lo:lo + gap, :] = 0
    with tempfile.TemporaryDirectory() as tmp:
        geometry.save_mask(mask.astype(bool), Path(tmp) / "m.bin")
        g, tau, steps = 1e-6, 0.8, 30000
        _run([exe, "--nx", nx, "--ny", ny, "--mask", Path(tmp) / "m.bin", "--periodic", 1,
              "--force", g, "--tau", tau, "--steps", steps, "--save_every", steps, "--out", tmp])
        m = _meta(tmp)
    k, k_exact = m["permeability"], gap ** 3 / (12.0 * ny)
    phi = m["porosity"]
    assert abs(phi - gap / ny) < 1e-9, f"porosity {phi} != {gap/ny}"
    # superficial must equal phi * pore-average
    assert abs(m["mean_ux"] - phi * m["mean_ux_pore"]) < 1e-12 * max(1, abs(m["mean_ux"]))
    err = abs(k - k_exact) / k_exact
    assert err < 0.03, f"Poiseuille permeability {k:.4f} vs exact {k_exact:.4f} (err {err:.2%})"
    return err


def test_rb_thermal_diffusion():
    """With buoyancy off, the Rayleigh-Benard temperature must DIFFUSE toward the linear
    conduction profile between the plates; with kappa=0 it must not. Catches the missing
    thermal-diffusion step."""
    exe = ROOT / "solvers" / "incompressible" / "ins2d"
    subprocess.run(["make", "-C", str(exe.parent)], check=True, capture_output=True)
    nx, ny, steps = 24, 32, 6000
    lin = np.linspace(1.0, 0.0, ny)[:, None] * np.ones((1, nx))   # hot plate (1) at j=0
    dev = {}
    for kappa in (0.0, 0.02):
        with tempfile.TemporaryDirectory() as tmp:
            _run([exe, "--mode", "rb", "--nx", nx, "--ny", ny, "--steps", steps,
                  "--save_every", steps, "--out", tmp, "--visc", 0.0, "--buoy", 0.0,
                  "--conf", 0, "--iters", 40, "--pert", 1.0, "--kappa", kappa])
            n = int(_meta(tmp)["nframes"])
            s = np.fromfile(Path(tmp) / f"frame_{n-1:05d}.bin", dtype=np.float32).reshape(ny, nx)
        dev[kappa] = float(np.sqrt(np.mean((s - lin) ** 2)))
    assert dev[0.02] < 0.5 * dev[0.0], f"diffusion did not act: rms dev kappa=0: {dev[0.0]:.3f}, kappa=0.02: {dev[0.02]:.3f}"
    return dev


def test_spectral_axes_and_vorticity():
    """Spectral solver works in [x,y]; the public arrays are [y,x]. After the boundary
    transpose, the renderer's finite-difference vorticity (with the physical spacing)
    must reproduce the solver's spectral vorticity for an asymmetric field."""
    from flowzoo.spectral import Spectral2D
    from flowzoo import render
    n = 128; L = 2 * np.pi; sim = Spectral2D(n=n, L=L, nu=0.0)
    x = np.linspace(0, L, n, endpoint=False); X, Y = np.meshgrid(x, x, indexing="ij")  # solver [x,y]
    w = np.sin(X) + 2.0 * np.cos(2 * Y)              # deliberately asymmetric in x vs y
    wh = np.fft.fft2(w)
    u, v = sim.velocity(wh)
    w_render = render.vorticity(u.T, v.T, dx=L / n)  # public [y,x] + spacing
    w_true = sim.vorticity(wh).T
    err = np.max(np.abs(w_render - w_true)) / np.max(np.abs(w_true))
    assert err < 0.02, f"vorticity convention/spacing mismatch: rel err {err:.3f}"
    # and the wrong (untransposed / unit-spacing) path really is different
    w_bad = render.vorticity(u, v)
    assert np.max(np.abs(w_bad - w_true)) / np.max(np.abs(w_true)) > 0.5
    return err


def test_spectral_fixed_end_time():
    """The same preset must reach the same simulated end time at every resolution."""
    import flowzoo.engine as engine
    base = None   # the spectral runner is the one exhibit with an "init" (initial-field) control
    for name, ex in engine.EXHIBITS.items():
        names = {q["name"] for q in ex["params"]}
        if "init" in names and "perturbation" in names and "viscosity" in names:
            base = {q["name"]: q["default"] for q in ex["params"]}; break
    assert base is not None, "spectral exhibit not found"
    ends = {}
    for res in list(engine.RES)[:2]:
        p = dict(base); p.update({"resolution": res, "duration": 0.02})
        r = engine._solve_spectral(p, lambda *_: None, None)
        ends[res] = (r.hints["T_end"], r.hints["times"][-1], r.raw[0][0].shape)
    T = [e[0] for e in ends.values()]
    assert abs(T[0] - T[1]) < 1e-12, f"end time depends on resolution: {ends}"
    for T_end, t_last, shape in ends.values():
        assert abs(t_last - T_end) <= 1.0001 * (T_end / 10), f"last frame {t_last} far from T_end {T_end}"
    return ends


def test_text_geometry_font_fallback():
    """Text obstacles must render even when no system font exists (Windows/macOS):
    fall back to the font bundled with Matplotlib."""
    from flowzoo import geometry
    saved = list(geometry._FONT_CANDIDATES)
    try:
        geometry._FONT_CANDIDATES[:] = ["/definitely/not/a/font.ttf"]
        m = geometry.text(240, 80, "Funoos")
    finally:
        geometry._FONT_CANDIDATES[:] = saved
    assert m.shape == (80, 240) and 0.01 < m.mean() < 0.6, "text mask not rendered"


def test_run_history_bounded():
    from funoos_app import _bound_runs, MAX_RUNS
    runs = {f"r{i}": i for i in range(MAX_RUNS + 4)}
    _bound_runs(runs)
    assert len(runs) == MAX_RUNS and list(runs) == [f"r{i}" for i in range(4, MAX_RUNS + 4)]


def test_mixing_bands_orientation():
    """The dye starts as HORIZONTAL bands (a function of y). In the public [y,x] arrays
    each row must therefore be uniform and rows must differ. Catches the untransposed
    [x,y] dye field, which drew the bands vertically."""
    import flowzoo.engine as engine
    base = None
    for name, ex in engine.EXHIBITS.items():
        if "bands" in {q["name"] for q in ex["params"]}:
            base = {q["name"]: q["default"] for q in ex["params"]}; break
    assert base is not None, "mixing exhibit not found"
    p = dict(base); p.update({"resolution": "Low (fast)", "duration": 0.01})
    r = engine._solve_mixing(p, lambda *_: None, None)
    c0 = r.raw[0]
    assert c0.std(axis=1).max() < 1e-9, "rows not uniform: bands are not horizontal"
    assert c0.std(axis=0).mean() > 0.1, "rows identical: no bands along y"
    assert abs(r.hints["T_end"] - 2600 * 0.01 * 0.4 * (2 * np.pi / 256)) < 1e-12


if __name__ == "__main__":
    print("poiseuille permeability: PASS  (err %.2f%%)" % (100 * test_permeability_poiseuille()))
    print("rb thermal diffusion: PASS  (rms dev %s)" % test_rb_thermal_diffusion())
    print("spectral axes/vorticity: PASS  (err %.4f)" % test_spectral_axes_and_vorticity())
    print("spectral fixed end time: PASS  %s" % test_spectral_fixed_end_time())
    test_text_geometry_font_fallback(); print("text font fallback: PASS")
    test_run_history_bounded(); print("run history bounded: PASS")
    test_mixing_bands_orientation(); print("mixing bands orientation: PASS")
