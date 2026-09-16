"""Case-level checks backing the scene registry's stated status (run: python tests/test_cases.py).

Each test pins a claim made in a scene's "Checks and limitations" layer:
  * Sod shock tube: density AND velocity errors against the exact Riemann solution.
  * Taylor–Green: energy decay against E0·exp(−4νt) (analytical).
  * Dye, diffusion only: stripe variance decays as exp(−2κm²t) (analytical).
  * Heated layer, buoyancy off: linear profile kept, Nu = 1 (analytical baseline).
  * Porous: directional permeability k_x ≫ k_y on a slab sample; k independent of the
    driving strength (Darcy linearity); disconnected geometry gives k ≈ 0.
  * SPH still water: residual speed and surface level.
  * Airfoil: lift changes sign with the angle of attack (mirror test).
  * Registry: every scene has the layered fields and a valid status.
"""
import math
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import engine, postproc, catalog, validate, geometry   # noqa: E402

_ENV = {**os.environ, "OMP_NUM_THREADS": "4"}
engine._ENV["OMP_NUM_THREADS"] = "4"


def test_spectral_stays_finite_beyond_the_explicit_diffusion_limit():
    """ν k_max² dt ≈ 2.85 exceeds the explicit-RK4 diffusion limit; the integrating-factor
    scheme must still produce finite fields (Ultra/ν=0.01 reproduced at Low with ν=0.03)."""
    r = engine.solve_exhibit("Cloud Billows", {"resolution": "Low (fast)", "viscosity": 0.03, "duration": 0.05})
    assert all(np.isfinite(u).all() and np.isfinite(v).all() for u, v in r.raw)
    n = r.raw[0][0].shape[0]; kmax = n // 2
    print(f"    spectral: ν·k_max²·dt = {0.03 * kmax ** 2 * r.hints['dt']:.2f}, all {r.nframes} frames finite")


def test_registry_complete():
    keys = set()
    for s in catalog.SCENES:
        assert s["key"] not in keys, "duplicate key"; keys.add(s["key"])
        for f in ("name", "method", "phenomenon", "exhibit", "preset", "question", "status", "blurb", "try", "observe", "checks", "refs"):
            assert s.get(f) not in (None, "", []), (s["key"], f)
        assert s["status"] in catalog.STATUS_LABEL and s["phenomenon"] in catalog.PHENOMENA
        assert s["exhibit"] in engine.EXHIBITS, s["key"]
        L = catalog.scene_layers(s["key"])["layers"]
        assert [x["id"] for x in L] == ["question", "see", "try", "observe", "physics", "model", "setup", "numerics", "refs"]
        assert L[6]["ic"] and L[6]["bc"], (s["key"], "initial and boundary conditions must be stated")
    c = catalog.counts()
    assert c["presets"] == len(catalog.SCENES) and c["methods"] == 6 and c["experiments"] == len(catalog.EXPERIMENTS) == 28
    assert catalog.check_experiments() == [], catalog.check_experiments()
    assert sum(len(e["presets"]) for e in catalog.EXPERIMENTS) == len(catalog.SCENES), "every scene is in exactly one experiment"
    ex = catalog.experiments()
    assert all(e["n_presets"] >= 1 and e["question"] and e["phenomenon"] in catalog.PHENOMENA for e in ex)
    assert catalog.experiment_of("lbm_airfoil_neg")["id"] == "airfoil_lift" and catalog.preset_label("lbm_airfoil_neg") == "−14°"


def test_sod_density_and_velocity_errors():
    res = engine.solve_exhibit("Shock Tube", {"resolution": "Medium"})
    m = postproc.metrics(res)
    assert m["sod_err_rho"] < 0.006 and m["sod_err_u"] < 0.01, m
    lo = engine.solve_exhibit("Shock Tube", {"resolution": "Low (fast)"})
    assert postproc.metrics(lo)["sod_err_rho"] > m["sod_err_rho"], "error falls with resolution"
    print(f"    sod: err_rho={m['sod_err_rho']:.4f} err_u={m['sod_err_u']:.4f} (600 cells)")


def test_taylor_green_analytical_decay():
    nu = 4e-4
    r = engine.solve_exhibit("Cloud Billows", {"init": "Taylor–Green vortex", "resolution": "Low (fast)", "duration": 0.3, "viscosity": nu})
    ke, _ = postproc._ke_enstrophy(r); t = np.asarray(r.times)
    pred = ke[0] * np.exp(-4 * nu * (t - t[0]))
    err = float(np.max(np.abs(ke - pred) / pred))
    assert err < 1e-6, err
    print(f"    taylor-green: max rel error {err:.1e}")


def test_dye_diffusion_only_analytical():
    kap, m = 4e-4, 6
    r = engine.solve_exhibit("Ink in Motion", {"resolution": "Low (fast)", "duration": 0.3, "stir": 0.0, "diffusion": kap, "bands": m})
    var = np.array([np.var(s) for s in r.raw]); t = np.asarray(r.times)
    # bands 0.5(1+sign(sin(m y))): the fundamental (wavenumber m) dominates; higher harmonics decay faster,
    # so after the first frames the variance ratio follows exp(-2 κ m² t) of the fundamental.
    k0 = len(t) // 2
    pred = var[k0] * np.exp(-2 * kap * m * m * (t[k0:] - t[k0]))
    err = float(np.max(np.abs(var[k0:] - pred) / pred))
    assert err < 0.03, err
    print(f"    dye diffusion-only: max rel error {err:.3f} vs exp(-2κm²t)")


def test_heated_layer_conduction_baseline():
    r = engine.solve_exhibit("Rayleigh-Benard", {"resolution": "Low (fast)", "duration": 0.3, "buoyancy": 0.0})
    f = postproc._rb_fluxes(r)
    lin = np.linspace(1, 0, len(f["T"]))
    assert float(np.sqrt(np.mean((f["T"] - lin) ** 2))) < 0.01, "profile stays linear"
    assert abs(f["Nu"] - 1.0) < 0.05, f["Nu"]
    print(f"    conduction baseline: Nu = {f['Nu']:.3f}")


def _perm(mask, fdir, force=1e-5, steps=3000):
    ny, nx = mask.shape
    with tempfile.TemporaryDirectory() as d:
        geometry.save_mask(mask, Path(d) / "m.bin")
        subprocess.run([str(ROOT / "solvers/lbm/lbm2d"), "--nx", str(nx), "--ny", str(ny), "--mask", str(Path(d) / "m.bin"),
                        "--periodic", "1", "--force", str(force), "--fdir", str(fdir), "--tau", "0.8",
                        "--steps", str(steps), "--save_every", str(steps), "--out", d], check=True, capture_output=True, env=_ENV)
        for line in (Path(d) / "meta.txt").read_text().splitlines():
            if line.startswith("permeability"):
                return float(line.split()[1])


def test_porous_direction_linearity_and_disconnected():
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/lbm")], check=True, capture_output=True)
    nx = ny = 48
    slabs = np.zeros((ny, nx), np.uint8); slabs[::12, :] = 1
    kx, ky = _perm(slabs, 0), _perm(slabs, 1)
    assert kx > 1.0 and ky < 1e-6 * kx, (kx, ky)
    k1, k2 = _perm(slabs, 0, 1e-5), _perm(slabs, 0, 2e-5)
    assert abs(k2 - k1) / k1 < 0.02, "Darcy linearity: k independent of the driving force"
    blocked = np.zeros((ny, nx), np.uint8); blocked[:, 20] = 1                      # a wall across the flow
    assert _perm(blocked, 0) < 1e-6 * kx, "disconnected geometry has zero permeability"
    print(f"    porous: k_x={kx:.3f} k_y={ky:.2e}  linearity {abs(k2 - k1) / k1:.1e}")


def test_sph_still_water():
    subprocess.run(["make", "-s", "-C", str(ROOT / "solvers/sph")], check=True, capture_output=True)
    r = engine.solve_exhibit("The Big Splash", {"scene": "Still water (hydrostatic)", "duration": 0.5, "particles": 1500})
    last = r.raw[-1]; Ly = r.hints["Ly"]
    vmax = float(last[:, 2].max()); surf = float(np.percentile(last[:, 1], 99))
    assert vmax < 0.05 * math.sqrt(9.81 * 0.42 * Ly), f"residual speed {vmax:.3f} m/s"
    assert abs(surf - 0.42 * Ly) < 0.05 * Ly, f"surface {surf:.3f} vs fill {0.42 * Ly:.3f}"
    print(f"    still water: max|v|={vmax:.3f} m/s, surface={surf:.2f} m (fill {0.42 * Ly:.2f})")


def test_airfoil_lift_changes_sign_with_angle():
    cl = {}
    for ang in (+12, -12):
        r = engine.solve_exhibit("Wind Tunnel", {"obstacle": "Airfoil", "angle": ang, "reynolds": 300, "resolution": "Low (fast)", "duration": 0.5})
        cl[ang] = postproc.metrics(r)["cl_circulation"]
    assert cl[12] > 0 > cl[-12], cl
    assert abs(abs(cl[12]) - abs(cl[-12])) < 0.5 * max(abs(cl[12]), abs(cl[-12])), cl
    print(f"    airfoil: C_l(+12°)={cl[12]:+.3f}  C_l(−12°)={cl[-12]:+.3f}")


def test_every_scene_fits_its_own_solver_limits():
    """The settings each scene hands to a solver must satisfy the solver's own preconditions.
    The Pouring scene once failed every run (exit code 2) because the tank became a 0.13 m glass
    while the width came from the dam-break control (1.0 m), which cannot fit inside it."""
    bad = []
    for sc in catalog.SCENES:
        ex = sc["exhibit"]
        params = {q["name"]: q["default"] for q in engine.EXHIBITS[ex]["params"]}
        params.update(sc["preset"])
        cfg = engine.effective(ex, params)
        if ex == "The Big Splash":
            Lx, Ly, a, H, dp = cfg["Lx"], cfg["Ly"], cfg["a"], cfg["H"], cfg["dp"]
            if not (0 < a <= Lx and 0 < H <= Ly):
                bad.append(f"{sc['key']}: a={a:.3f} H={H:.3f} do not fit the tank {Lx:.3f}x{Ly:.3f}")
            if dp <= 0 or (Lx / dp) * (Ly / dp) > 4.0e7:
                bad.append(f"{sc['key']}: dp={dp} gives too many particle sites")
        elif ex in ("Wind Tunnel", "Porous Flow"):
            if not (0.5 < cfg["tau"] <= 10.0):
                bad.append(f"{sc['key']}: tau={cfg['tau']} outside (0.5, 10]")
            if abs(cfg.get("U", 0.0)) > 0.5:
                bad.append(f"{sc['key']}: |U|={abs(cfg['U'])} above the lattice limit")
    assert not bad, "; ".join(bad)


def test_pouring_actually_runs():
    """A short Pouring run produces frames (it failed with exit code 2 in 1.2.0)."""
    sc = catalog.scene("sph_pour")
    params = {q["name"]: q["default"] for q in engine.EXHIBITS[sc["exhibit"]]["params"]}
    params.update(sc["preset"]); params["duration"] = 0.3
    res = engine.solve_exhibit(sc["exhibit"], params)
    assert res.nframes >= 2, res.nframes
    last = res.raw[-1]
    assert len(last) > 0, "no particles in the glass"


def test_tracer_pure_diffusion_matches_theory():
    """With the flow switched off, the plume variance must grow as 2·D_m·t (the analytic result),
    and tracer mass must be conserved."""
    from flowzoo import transport
    ny, nx = 48, 320
    solid = np.zeros((ny, nx), bool)
    u = np.zeros((ny, nx)); v = np.zeros((ny, nx))
    dm = 0.02
    tr = transport.Transport(u, v, solid, dm, axis="x")
    tr.c[:] = 0.0; tr.c[:, nx // 2] = 1.0
    m0 = tr.mass()
    for _ in range(3000):
        tr.step()
    _, var = tr.moments()
    expected = 2.0 * dm * tr.t
    assert abs(var / expected - 1.0) < 1e-3, (var, expected)
    assert abs(tr.mass() - m0) / m0 < 1e-12, tr.mass() - m0


def test_tracer_conserves_mass_and_stays_out_of_the_grains():
    """A pulse carried through a grain pack is accounted for exactly (injected = left + still
    inside) and never puts tracer inside a grain."""
    from flowzoo import transport
    ny, nx = 64, 200
    rng = np.random.default_rng(3)
    yy, xx = np.mgrid[0:ny, 0:nx]
    solid = np.zeros((ny, nx), bool)
    for _ in range(90):
        cx, cy, r = rng.integers(0, nx), rng.integers(0, ny), rng.uniform(3, 6)
        solid |= ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
    u = np.where(solid, 0.0, 0.01 * (1.0 + 0.5 * np.sin(2 * np.pi * yy / ny)))
    v = np.zeros_like(u)
    frames, times, rec = transport.run(u, v, solid, 1e-3, axis="x", injection="pulse", steps=2000, nframes=10)
    assert abs(rec["balance"][-1]) / rec["mass_in"][-1] < 1e-12, rec["balance"][-1]
    assert max(float(f[solid].max()) for f in frames) == 0.0
    assert len(frames) == len(times)


def test_tracer_disperses_more_than_molecular_diffusion():
    """Carried through the pore space, a plume must spread faster than molecular diffusion alone:
    that excess is the mechanical dispersion the velocity field produces."""
    from flowzoo import transport
    ny, nx = 64, 240
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:ny, 0:nx]
    solid = np.zeros((ny, nx), bool)
    for _ in range(80):
        cx, cy, r = rng.integers(0, nx), rng.integers(0, ny), rng.uniform(3, 6)
        solid |= ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
    u = np.where(solid, 0.0, 0.02 * (1.0 + 0.8 * np.sin(2 * np.pi * yy / ny)))   # fast and slow channels
    v = np.zeros_like(u)
    dm = 2e-3
    # the sample is periodic: stop while the plume is still travelling forward, before it wraps
    # around and overlaps itself (after that the variance of the profile stops meaning anything)
    probe = transport.Transport(u, v, solid, dm, axis="x")
    u_mean = float(np.abs(u[~solid]).mean())
    steps = int(0.35 * nx / (u_mean * probe.dt))
    _f, times, rec = transport.run(u, v, solid, dm, axis="x", injection="pulse", steps=steps, nframes=40)
    t = np.asarray(times); var = np.asarray(rec["variance_cells2"])
    half = slice(len(t) // 2, None)
    d_eff = float(np.polyfit(t[half], var[half], 1)[0]) / 2.0
    assert d_eff > 2.0 * dm, (d_eff, dm)
    assert d_eff > rec["numerical_diffusion"], (d_eff, rec["numerical_diffusion"])


def test_tracer_outlet_is_open_and_nothing_re_enters():
    """The sample has a real outlet: a pulse leaves and does not reappear upstream, a steady supply
    settles at the injected concentration without exceeding it, and the tracer is accounted for
    exactly in both cases."""
    from flowzoo import transport
    ny, nx = 48, 200
    rng = np.random.default_rng(11)
    yy, xx = np.mgrid[0:ny, 0:nx]
    solid = np.zeros((ny, nx), bool)
    for _ in range(60):
        cx, cy, r = rng.integers(0, nx), rng.integers(0, ny), rng.uniform(3, 6)
        solid |= ((xx - cx) ** 2 + (yy - cy) ** 2) <= r * r
    u = np.where(solid, 0.0, 0.02 * (1.0 + 0.6 * np.sin(2 * np.pi * yy / ny)))
    v = np.zeros_like(u)
    tr = transport.Transport(u, v, solid, 1e-3, axis="x").pulse(0.06)
    steps = int(2.5 * nx / (0.02 * tr.dt))
    for _ in range(steps):
        tr.step()
    assert tr.mass_out > 0.6 * tr.mass_in, (tr.mass_out, tr.mass_in)   # most of the slug has left
    early = float(tr.c[:, :nx // 10].sum())                            # the inlet end runs clean again
    assert early < 1e-3 * tr.mass_in, early
    assert abs(tr.balance()) / tr.mass_in < 1e-12, tr.balance()
    tr2 = transport.Transport(u, v, solid, 1e-3, axis="x").set_inlet(1.0)
    for _ in range(steps):
        tr2.step()
    assert 0.6 < tr2.outlet_concentration() <= 1.0 + 1e-9, tr2.outlet_concentration()
    # Nothing can exceed the injected concentration. The bound is the projection's residual
    # divergence, not round-off: whatever is left of ∇·u acts as dc/dt = −c ∇·u and compounds over
    # thousands of steps, so an iterative projection buys digits rather than an exact bound.
    assert float(tr2.c.max()) <= 1.0 + 1e-9, float(tr2.c.max()) - 1.0
    assert abs(tr2.balance()) / tr2.mass_in < 1e-10, tr2.balance()


def test_tracer_scene_runs_and_measures():
    """A short run of the shipped tracer scene produces frames, a breakthrough curve and a
    dispersion measurement."""
    from flowzoo import postproc
    sc = catalog.scene("tracer_pulse")
    params = {q["name"]: q["default"] for q in engine.EXHIBITS[sc["exhibit"]]["params"]}
    params.update(sc["preset"]); params["resolution"] = "Low (fast)"; params["duration"] = 0.3
    res = engine.solve_exhibit(sc["exhibit"], params)
    assert res.kind == "tracer" and res.nframes >= 5
    assert res.mask is not None and float(max(f[res.mask].max() for f in res.raw)) == 0.0
    m = postproc.metrics(res)
    assert m["peclet"] == params["peclet"]
    assert m.get("dispersion_cells2_per_step", 0) > 0, m
    assert m.get("tracer_mass_balance", 1.0) < 1e-9, m
    assert len(postproc.plots(res)) >= 2


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
