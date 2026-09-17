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


def test_tracer_outlet_draws_clean_water_not_the_feed():
    """A reversed outlet face draws water in from outside the sample, and outside is clean. Handing
    it the injected concentration puts tracer into the downstream end before any has travelled
    there, which is precisely what having an outlet is meant to prevent. A mass balance cannot
    catch this on its own: the tracer arrives through a counted boundary, so the books still close."""
    from flowzoo import transport
    u = np.full((16, 128), 0.02)
    u[0, :] = -0.002                                   # one lane runs backwards through the outlet
    tr = transport.Transport(u, np.zeros_like(u), np.zeros_like(u, bool), 1e-3)
    assert int((tr.uf_boundary < 0).sum()) > 0, "this test needs a reversed outlet face to mean anything"
    tr.set_inlet(1.0).step()
    assert float(tr.c[:, -1].max()) == 0.0, float(tr.c[:, -1].max())
    assert tr.outlet_in == 0.0, tr.outlet_in


def test_tracer_step_is_monotone_when_advection_and_diffusion_act_together():
    """Satisfying the Courant limit and the diffusive limit separately is not enough: acting
    together they can drain a cell past zero in one step. Clipping the result back to zero would
    hide that and create tracer, since the clip adds back exactly what it removes."""
    from flowzoo import transport
    u = np.ones((16, 16))
    tr = transport.Transport(u, u, np.zeros_like(u, bool), 0.25)
    tr.c[8, 8] = 1.0
    tr.mass_initial = 1.0
    tr.step()
    assert float(tr.c.min()) >= 0.0, float(tr.c.min())
    assert abs(tr.mass() - 1.0) < 1e-12, tr.mass()
    assert tr.clipped_mass == 0.0, tr.clipped_mass


def test_plume_moments_weigh_tracer_not_pore_averaged_concentration():
    """Slices of the sample hold different amounts of pore space. Averaging concentration within a
    slice before taking moments gives a slice with one pore cell the same say as a slice with
    twenty, and puts the plume in the wrong place."""
    from flowzoo import transport
    ny, nx = 4, 8
    solid = np.ones((ny, nx), bool)
    solid[0, 0] = False                                # one pore cell at x = 0
    solid[0:3, 4] = False                              # three pore cells at x = 4
    z = np.zeros((ny, nx))
    tr = transport.Transport(z, z, solid, 1e-3, axis="x", project_field=False)
    tr.c[~solid] = 1.0
    centre, _ = tr.moments()
    assert abs(centre - 3.0) < 1e-12, centre           # (1 cell at 0 + 3 cells at 4) / 4 cells


def test_unstable_wind_tunnel_stops_instead_of_returning_non_finite_frames():
    """A setting the validator accepts can still go unstable. When it does the run has to stop and
    say so: returning frames full of non-finite values lets the app render a video of a calculation
    that never happened, and reports it as a completed experiment."""
    from flowzoo import schema
    v = schema.validate("Wind Tunnel", dict(resolution="Low (fast)", duration=0.2,
                                            reynolds=1200, speed=0.15, size=0.3))
    assert v.ok, v.errors
    try:
        res = engine.solve_exhibit("Wind Tunnel", v.params)
    except engine.SolverError as e:
        assert e.returncode == 4, e.returncode
        assert "unstable" in str(e).lower(), str(e)
    else:
        bad = [i for i, f in enumerate(res.raw) if not np.isfinite(np.asarray(f)).all()]
        assert not bad, f"{len(bad)} of {len(res.raw)} frames were non-finite yet returned as a result"


def test_sph_frames_hold_one_state_per_time():
    """Each saved state belongs to one time. The solver saved once before the update and once after
    it, labelling both with the time before, so half of every run's frames were a second state
    stamped with a time already written, and the loop ran one update more than it was asked for."""
    from collections import Counter
    from flowzoo import schema
    p = {q["name"]: q["default"] for q in engine.EXHIBITS["The Big Splash"]["params"]}
    p.update({"scene": "Dam break", "particles": 600, "duration": 0.05})
    res = engine.solve_exhibit("The Big Splash", schema.validate("The Big Splash", p).params)
    t = list(res.times)
    repeats = [x for x, c in Counter(t).items() if c > 1]
    assert not repeats, f"{len(repeats)} timestamps carry more than one state"
    assert all(b > a for a, b in zip(t, t[1:])), "frame times must strictly increase"
    assert t[0] == 0.0, t[0]


def test_gray_scott_first_frame_is_the_initial_state():
    """The frame labelled t = 0 is the state before anything is done to it. It used to be one
    update old, so a blob interior seeded at 0.25 was returned as 0.25625, and the final state was
    kept only when the step count happened to land on the frame interval."""
    from flowzoo.reaction import gray_scott
    frames, times = gray_scott(n=64, F=0.035, k=0.065, steps=0, nframes=1, seed=5,
                               nseeds=1, noise=0.0)
    assert len(frames) == 1 and times == [0.0], (len(frames), times)
    first = float(np.asarray(frames[0]).max())
    assert abs(first - 0.25) < 1e-12, first
    frames, times = gray_scott(n=48, F=0.035, k=0.065, steps=7, nframes=3, seed=1,
                               nseeds=1, noise=0.0)
    assert len(frames) == len(times), (len(frames), len(times))
    assert times[0] == 0.0 and times[-1] == 7.0, times        # the final state is always kept
    assert all(b > a for a, b in zip(times, times[1:])), times


def test_tracer_reports_when_the_frozen_flow_is_not_creeping():
    """Holding the flow fixed is exact only for slow, settled flow. Settings well inside the
    recommended ranges reach pore Reynolds numbers of order ten with the permeability still moving,
    and the run has to say so rather than presenting its numbers as the creeping-flow experiment."""
    from flowzoo import schema, postproc
    p = {q["name"]: q["default"] for q in engine.EXHIBITS["Tracer in Rock"]["params"]}
    p.update({"resolution": "Low (fast)", "porosity": 0.85, "grain": 0.07, "strength": 4,
              "seed": 1, "duration": 0.2})
    v = schema.validate("Tracer in Rock", p)
    assert v.ok and not v.warnings, (v.errors, v.warnings)   # nothing warns the user beforehand
    res = engine.solve_exhibit("Tracer in Rock", v.params)
    assert res.hints["pore_reynolds"] > 1.0, res.hints["pore_reynolds"]
    assert res.hints["flow_settled"] is False, res.hints["k_status"]
    text = [t for t in postproc.plots(res) if t[0].startswith("Breakthrough")][0][2]
    assert "qualitative" in text, text[-240:]


def test_tracer_says_how_much_of_the_crossing_it_covered():
    """At low Péclet the diffusive limit makes the step small and the step budget binds, so the run
    covers a fraction of a pore-volume crossing. Reporting that as the requested experiment is what
    makes a Péclet comparison meaningless, since the runs cover different ground."""
    from flowzoo import schema
    p = {q["name"]: q["default"] for q in engine.EXHIBITS["Tracer in Rock"]["params"]}
    p.update({"resolution": "Low (fast)", "peclet": 0.1, "duration": 0.3})
    res = engine.solve_exhibit("Tracer in Rock", schema.validate("Tracer in Rock", p).params)
    h = res.hints
    assert h["truncated"] is True, (h["steps_requested"], h["steps_run"])
    assert h["crossings_run"] < h["crossings_requested"], (h["crossings_run"], h["crossings_requested"])


def test_spectral_products_do_not_alias_into_the_retained_band():
    """The 2/3 rule only dealiases if the state is truncated before products are formed. Masking
    the result instead lets modes above the cutoff multiply each other down into the retained band,
    where the mask cannot tell that energy from a real interaction between resolved modes."""
    from flowzoo.spectral import Spectral2D
    n = 64
    sp = Spectral2D(n=n, nu=0.0)
    x = np.arange(n) * 2 * np.pi / n
    X, Y = np.meshgrid(x, x, indexing="xy")
    wh = np.fft.fft2(np.sin(25 * X) + np.sin(25 * X + Y))      # energy only above the cutoff
    kept = np.abs(sp.nonlinear(wh)) * sp.mask / (n * n)
    assert float(kept.max()) < 1e-20, float(kept.max())


def test_euler_held_blocks_neither_gain_nor_lose():
    """A face against a held block is a wall. Solved as an ordinary Riemann problem between two
    fluids it carried mass and energy into the block, and the reset applied after each stage
    absorbed the difference, so nothing in the output ever showed it."""
    import subprocess, tempfile
    from pathlib import Path
    exe = engine._bin("compressible", "euler2d")
    d = tempfile.mkdtemp(prefix="wall_")
    nx, ny = 120, 80
    r = subprocess.run([str(exe), "--nx", str(nx), "--ny", str(ny), "--steps", "300",
                        "--save_every", "100", "--mode", "blast", "--building", "1",
                        "--strength", "500", "--p0", "3", "--out", d],
                       capture_output=True, text=True)
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])
    sb = np.fromfile(Path(d, "solid.bin"), dtype=np.float32).reshape(ny, nx) > 0.5
    fin = np.fromfile(Path(d, "final.bin"), dtype=np.float32).reshape(ny, nx)
    assert int(sb.sum()) > 100, int(sb.sum())          # the test needs blocks to be worth anything
    held = fin[sb]
    assert float(held.min()) == 6.0 and float(held.max()) == 6.0, (float(held.min()), float(held.max()))
    assert np.isfinite(fin).all()


def test_euler_reported_extrema_cover_the_whole_run():
    """The reported minima describe the run, not the frames that happened to be saved. Scanning
    only on saving steps skipped every step in between and the separately saved final state, so
    the metadata could claim a higher minimum than the final field itself contains."""
    import subprocess, tempfile
    from pathlib import Path
    exe = engine._bin("compressible", "euler2d")
    d = tempfile.mkdtemp(prefix="extrema_")
    nx, ny = 120, 80
    r = subprocess.run([str(exe), "--nx", str(nx), "--ny", str(ny), "--steps", "300",
                        "--save_every", "97", "--mode", "blast", "--p0", "12", "--out", d],
                       capture_output=True, text=True)      # 300 is not a multiple of 97, so the
    assert r.returncode == 0, (r.returncode, r.stderr[-300:])   # final state is saved separately
    meta = {}
    for line in Path(d, "meta.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) == 2:
            meta[parts[0]] = parts[1]
    fin = np.fromfile(Path(d, "final.bin"), dtype=np.float32).reshape(ny, nx)
    assert float(meta["rhomin"]) <= float(fin.min()) + 1e-6, (meta["rhomin"], float(fin.min()))


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
