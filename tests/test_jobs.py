"""Job-lifecycle tests for the desktop backend (run with: python tests/test_jobs.py).

Covers the Stage-2 requirements: explicit job states, immutable parameter
snapshots, cancellation that really stops the solver (C++ subprocess and
in-process loops), error envelopes instead of exceptions, request tokens echoed
for stale-response filtering, the bounded/pinnable result store and crash
cleanup of scratch directories. No GUI is needed: `Api` is driven directly.
"""
import os
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import funoos_app                                   # noqa: E402
from funoos_app import Api, RunStore, Job, sweep_stale_temp, result_bytes   # noqa: E402
from flowzoo import engine                          # noqa: E402

# A stand-in "C++ solver": prints step X/Y slowly so cancellation has something to interrupt.
FAKE_SOLVER = [sys.executable, "-u", "-c",
               "import time\nfor i in range(1, 201):\n    print(f'step {i}/200', flush=True); time.sleep(0.05)"]


def FakeResult(nframes=3, tag="fake"):
    """A small real engine.Result (kind lbm) so views, previews and metadata resolve."""
    yy, xx = np.mgrid[0:8, 0:8]
    raw = [(np.sin(xx / 3.0 + 0.1 * i).astype(np.float32), np.cos(yy / 3.0).astype(np.float32)) for i in range(nframes)]
    return engine.Result("lbm", raw, f"{tag}  8×8", hints={"dx": 1.0}, times=[float(i) for i in range(nframes)])


def _install_fake_exhibits():
    """Register in-process fake exhibits on the engine: quick, slow (cancellable), failing."""
    def quick(p, pr, tmp):
        pr("quick 0%"); return FakeResult(tag=f"quick {p.get('a')}")

    def slow(p, pr, tmp):
        for i in range(200):
            pr(f"simulating… {i // 2}%")            # cooperative cancel point
            time.sleep(0.02)
        return FakeResult(tag="slow")

    def subproc(p, pr, tmp):
        engine._run_solver(FAKE_SOLVER, pr)         # the C++ path: killed on cancel
        return FakeResult(tag="subproc")

    def failing(p, pr, tmp):
        raise RuntimeError("boom: solver blew up\nsecond line")

    for name, fn in [("__quick__", quick), ("__slow__", slow), ("__subproc__", subproc), ("__fail__", failing)]:
        engine.EXHIBITS[name] = {"params": [{"name": "a", "default": 1}], "solve": fn}


_install_fake_exhibits()
_ENCODES = []
def _fake_mp4(frames, fps):                       # no ffmpeg needed; consume the generator like the real one
    n = sum(1 for _ in frames); _ENCODES.append(n)
    return f"data:video/mp4;base64,{n}"
funoos_app._b64_mp4 = _fake_mp4


def _api():
    return Api(store=RunStore(max_runs=3, max_bytes=10 ** 9), sweep=False)


# ----------------------------------------------------------------- engine level
def test_run_solver_cancel_kills_process():
    """Setting the cancel event stops a running solver subprocess promptly and raises Cancelled."""
    ev = threading.Event(); seen = []
    def pr(m): seen.append(m)
    pr.cancel = ev
    t0 = time.time()
    threading.Timer(0.5, ev.set).start()
    try:
        engine._run_solver(FAKE_SOLVER, pr)
        raise AssertionError("expected Cancelled")
    except engine.Cancelled:
        pass
    dt = time.time() - t0
    assert dt < 3.0, f"cancel took {dt:.1f}s (solver would have run 10s)"
    assert any("simulating" in m for m in seen), "progress was streamed before cancel"
    assert not engine._LIVE_PROCS, "process bookkeeping cleared"


def test_run_solver_completes_and_reports_progress():
    quick = [sys.executable, "-c", "for i in range(1, 6): print(f'step {i}/5')"]
    seen = []
    engine._run_solver(quick, seen.append)
    assert seen == [f"simulating… {p}%" for p in (20, 40, 60, 80, 99)], seen   # 100% is clamped to 99


def test_run_solver_failure_raises():
    bad = [sys.executable, "-c", "import sys; print('step 1/2'); sys.exit(3)"]
    try:
        engine._run_solver(bad, lambda m: None)
        raise AssertionError("expected CalledProcessError")
    except subprocess.CalledProcessError as e:
        assert e.returncode == 3


def test_solve_exhibit_cancel_in_process():
    """In-process solvers stop at their next progress report once the event is set."""
    ev = threading.Event()
    threading.Timer(0.2, ev.set).start()
    t0 = time.time()
    try:
        engine.solve_exhibit("__slow__", {}, progress=lambda m: None, cancel=ev)
        raise AssertionError("expected Cancelled")
    except engine.Cancelled:
        pass
    assert time.time() - t0 < 2.0


# ----------------------------------------------------------------- Api level
def test_job_states_and_snapshot():
    api = _api()
    params = {"a": 5}
    r = api.run("__quick__", params, None, None, 26, "job-A")
    assert r["ok"] and r["state"] == "completed" and r["job_id"] == "job-A" and r["run_id"] == "job-A"
    assert r["params"] == {"a": 5} and "video" in r and r["views"]
    params["a"] = 99                                     # caller mutates its dict after the run started
    j = api.job("job-A")
    assert j["ok"] and j["params"] == {"a": 5}, "job keeps an immutable snapshot"
    assert [h["state"] for h in j["history"]] == ["preparing", "running", "rendering", "completed"]
    assert "job-A" in api.store


def test_cancel_stops_job_and_keeps_previous_result():
    api = _api()
    first = api.run("__quick__", {"a": 1}, None, None, 26, "first")
    assert first["ok"]
    out = {}
    th = threading.Thread(target=lambda: out.update(api.run("__subproc__", {}, None, None, 26, "second")))
    th.start(); time.sleep(0.6)
    c = api.cancel("second")
    assert c["ok"] and c["cancel_requested"] and c["state"] == "running"
    th.join(timeout=5); assert not th.is_alive(), "run returned after cancel"
    assert out["ok"] is False and out["state"] == "cancelled" and out["error"] == "cancelled"
    assert api.job("second")["state"] == "cancelled"
    assert "second" not in api.store and "first" in api.store, "previous completed result is kept"
    assert not engine._LIVE_PROCS, "no solver process left behind"


def test_cancel_in_process_job():
    api = _api()
    out = {}
    th = threading.Thread(target=lambda: out.update(api.run("__slow__", {}, None, None, 26, "slow1")))
    th.start(); time.sleep(0.3); api.cancel("slow1"); th.join(timeout=5)
    assert not th.is_alive() and out["state"] == "cancelled"


def test_new_run_supersedes_active_job():
    """Starting another run cancels the one in flight (single worker policy)."""
    api = _api()
    out = {}
    th = threading.Thread(target=lambda: out.update(api.run("__slow__", {}, None, None, 26, "old")))
    th.start(); time.sleep(0.3)
    new = api.run("__quick__", {}, None, None, 26, "new")
    th.join(timeout=5)
    assert new["ok"] and out["state"] == "cancelled"


def test_failure_is_an_envelope_not_an_exception():
    api = _api()
    r = api.run("__fail__", {}, None, None, 26, "f1")
    assert r["ok"] is False and r["state"] == "failed"
    assert r["error"] == "RuntimeError: boom: solver blew up", r["error"]   # first line only
    assert api.job("f1")["state"] == "failed" and "f1" not in api.store
    r2 = api.run("__does_not_exist__", {}, None, None, 26, "f2")
    assert r2["ok"] is False and r2["state"] == "failed" and "unknown exhibit" in r2["error"]


def test_unknown_or_bad_job_ids():
    api = _api()
    assert api.cancel("nope")["ok"] is False and api.job("nope")["ok"] is False
    r = api.run("__quick__", {}, None, None, 26, "bad id with spaces!")
    assert r["ok"] and r["job_id"] != "bad id with spaces!" and len(r["job_id"]) == 12
    r2 = api.run("__quick__", {}, None, None, 26, r["job_id"])   # duplicate id -> a fresh one is minted
    assert r2["ok"] and r2["job_id"] != r["job_id"] and len(api.jobs()["jobs"]) == 2


def test_request_tokens_echoed_and_expired_runs():
    api = _api()
    r = api.run("__quick__", {}, None, None, 26, "t1")
    v = api.render_view("t1", "Vorticity", "Turbo", 26, req=7)
    assert v["ok"] and v["req"] == 7 and v["view"] == "Vorticity" and v["cmap"] == "Turbo"
    v2 = api.render_view("t1", "No such view", "no such cmap", 26, req=8)
    assert v2["ok"] and v2["view"] == r["views"][0] and v2["cmap"] == engine.DEFCMAP["lbm"]
    gone = api.render_view("zzz", "Vorticity", None, 26, req=9)
    assert gone == {"ok": False, "error": "run expired", "run_id": "zzz", "req": 9}
    assert api.diagnostics("zzz", req=3)["ok"] is False and api.diagnostics("zzz", req=3)["req"] == 3
    assert api.save_clip("zzz", "Vorticity")["ok"] is False
    d = api.scene_detail("__no_such_scene__", req=11)
    assert d["ok"] is False and d["req"] == 11
    real = funoos_app.catalog.by_method()
    key = next(iter(real.values()))[0]["key"]
    d2 = api.scene_detail(key, req=12)
    assert d2["ok"] and d2["req"] == 12 and d2["params"]


def test_diagnostics_envelope():
    api = _api()
    api.run("__quick__", {}, None, None, 26, "d1")
    funoos_app.postproc.plots, orig = (lambda res: [("T", np.zeros((4, 4, 3), np.uint8), "why")]), funoos_app.postproc.plots
    try:
        d = api.diagnostics("d1", req=1)
    finally:
        funoos_app.postproc.plots = orig
    assert d["ok"] and d["req"] == 1 and d["plots"][0]["title"] == "T" and d["plots"][0]["img"].startswith("data:image/png")


def test_view_cache_preview_and_superseded():
    api = _api()
    r = api.run("__quick__", {}, None, "Turbo", 26, "vc")
    assert r["ok"] and r["meta"]["frames"] == 3 and r["defcmap"] == "Turbo"
    n0 = len(_ENCODES)
    v0 = api.render_view("vc", "Vorticity", "Turbo", 26, req=0)
    assert v0["ok"] and v0["cached"] is True, "the clip encoded by run() itself is already cached"
    a = api.render_view("vc", "Speed", "Turbo", 26, req=1)
    assert a["ok"] and a["cached"] is False and len(_ENCODES) == n0 + 1
    b = api.render_view("vc", "Speed", "Turbo", 26, req=2)
    assert b["ok"] and b["cached"] is True and len(_ENCODES) == n0 + 1, "second identical request is served from cache"
    c = api.render_view("vc", "Speed", "Inferno", 26, req=3)
    assert c["ok"] and c["cached"] is False, "a different palette is a different clip"
    d = api.render_view("vc", "Speed", "Inferno", 26, req=4, vmin=0, vmax=0.5)
    assert d["ok"] and d["cached"] is False, "manual limits are part of the key"
    p = api.preview_frame("vc", "Speed", "Magma", 0.5, req=9)
    assert p["ok"] and p["req"] == 9 and p["index"] == 1 and p["time"] == 1.0 and p["img"].startswith("data:image/png")
    assert api.preview_frame("nope", "Speed")["ok"] is False
    # a request superseded before its encode starts is abandoned, not encoded
    api._latest["vc"] = 99
    s = api.render_view("vc", "Streamlines", "Turbo", 26, req=50)
    assert s["ok"] is False and s.get("superseded") is True
    # eviction drops the cached clips of that run
    api.store.remove("vc"); api.views.drop_run("vc")
    assert len(api.views) == 0


def test_estimate_api():
    api = _api()
    e = api.estimate("Wind Tunnel", {"resolution": "Low (fast)"})
    assert e["ok"] and e["grid"] == [540, 180] and e["seconds"] > 0
    assert api.estimate("__nope__", {})["ok"] is False


def test_run_emits_preview_before_clip():
    api = _api(); seen = []
    api._emit_preview = lambda jid, png, label: seen.append((jid, png[:15], label))
    r = api.run("__quick__", {}, None, None, 26, "pv")
    assert r["ok"] and seen and seen[0][0] == "pv" and seen[0][1] == "data:image/png;" and "encoding" in seen[0][2]


def test_project_record_roundtrip():
    api = _api()
    rec = api.project("lbm_cylinder", "Wind Tunnel", {"reynolds": 120}, "Vorticity", "Turbo", False)
    assert rec["app"] == "Funoos" and rec["version"] and rec["params"]["reynolds"] == 120 and rec["derived"]
    assert "lbm2d" in rec["solver_versions"]
    with tempfile.TemporaryDirectory() as d:
        import json
        pth = Path(d) / "x.funoos.json"; pth.write_text(json.dumps(rec))
        got = api.load_project_file(pth)
        assert got["ok"] and got["config"]["params"]["reynolds"] == 120 and got["config"]["validation"]["ok"]
        (Path(d) / "bad.json").write_text("{}")
        assert api.load_project_file(Path(d) / "bad.json")["ok"] is False


def test_sweep_runs_each_value_and_is_cancellable():
    api = Api(store=RunStore(max_runs=10, max_bytes=10 ** 9), sweep=False)
    r = api.sweep("__quick__", {}, "a", [1, 2, 3], None, None, "sw1")
    assert r["ok"] and len(r["items"]) == 3 and [it["value"] for it in r["items"]] == [1, 2, 3]
    assert all(it["frame"].startswith("data:image/png") for it in r["items"])
    assert all(it["run_id"] in api.store for it in r["items"]) and api.job("sw1")["state"] == "completed"
    assert api.sweep("__quick__", {}, "a", list(range(20)), None, None, "sw2")["items"].__len__() == api.MAX_SWEEP
    assert api.sweep("__quick__", {}, "a", ["x"], None, None, "sw3")["ok"] is False
    out = {}
    th = threading.Thread(target=lambda: out.update(api.sweep("__slow__", {}, "a", [1, 2, 3], None, None, "sw4")))
    th.start(); time.sleep(0.4); api.cancel("sw4"); th.join(timeout=10)
    assert not th.is_alive() and out["state"] == "cancelled" and api.job("sw4")["state"] == "cancelled"


def test_compare_probe_inspect_profile():
    api = _api()
    a = api.run("__quick__", {"a": 1}, None, None, 26, "ca"); b = api.run("__quick__", {"a": 2}, None, None, 26, "cb")
    assert a["ok"] and b["ok"]
    n0 = len(_ENCODES)
    c = api.compare("ca", "cb", "Speed", "Turbo", 26, req=4)
    assert c["ok"] and c["req"] == 4 and "shared interval" in c["note"] and len(_ENCODES) == n0 + 1 and _ENCODES[-1] == 3
    assert api.compare("ca", "zz", "Speed")["ok"] is False
    i = api.inspect("ca", "Speed", 0.03, 0.5, 1.0, req=1)        # the 8-cell field is ~7 % of the frame width
    assert i["ok"] and not i["outside"] and i["value"] is not None and i["label"] == "speed |u|"
    assert api.inspect("ca", "Speed", 0.99, 0.5)["outside"] is True, "the colourbar panel is not part of the field"
    pr = api.probe("ca", "Vorticity", 0.3, 0.5, req=2)
    assert pr["ok"] and len(pr["values"]) == 3 and pr["plot"].startswith("data:image/png") and pr["times"] == [0.0, 1.0, 2.0]
    lp = api.line_profile("ca", "Speed", "x", 0.5, 1.0, req=3)
    assert lp["ok"] and len(lp["values"]) == 8 and lp["plot"]
    lp2 = api.line_profile("ca", "Speed", "y", 0.5, 0.0)
    assert lp2["ok"] and lp2["index"] == 0 and len(lp2["values"]) == 8
    assert api.probe("zz", "Speed", 0.5, 0.5)["ok"] is False


class _FakeWin:
    """Stands in for the pywebview window: every save dialog picks a file in `d`."""
    def __init__(self, d): self.d = d
    def create_file_dialog(self, kind, save_filename="x", file_types=(), allow_multiple=False):
        return str(Path(self.d) / save_filename)
    def evaluate_js(self, js): pass


def test_exports_are_traceable_to_the_run():
    import json
    api = _api(); r = api.run("__quick__", {"a": 2}, None, None, 26, "ex1"); assert r["ok"]
    with tempfile.TemporaryDirectory() as d:
        api._win = _FakeWin(d)
        p = api.save_png("ex1", "Speed", "Turbo", 0.5); assert p["ok"] and Path(p["path"]).stat().st_size > 100 and p["index"] == 1
        s = api.save_plots_svg("ex1"); assert s["ok"] and s["paths"] and all(Path(x).read_text().startswith("<?xml") for x in s["paths"])
        z = api.save_arrays("ex1"); assert z["ok"] and {"ux", "uy", "x", "y", "times", "meta_json"} <= set(z["arrays"])
        data = np.load(z["path"]); meta = json.loads(str(data["meta_json"]))
        assert data["ux"].shape == (3, 8, 8) and meta["kind"] == "lbm" and "time_unit" in meta and len(data["times"]) == 3
        c = api.export_csv("ex1", "series", {}); assert c["ok"] and "time" in Path(c["path"]).read_text().splitlines()[0]
        rp = api.save_report("ex1", "lbm_cylinder", "Speed", "Turbo")
        html = Path(rp["path"]).read_text(); assert rp["ok"] and "ex1" in html and "Measurements" in html and "Checks and limitations" in html
        # clip options: frame window, fps and scale reach the encoder
        n0 = len(_ENCODES)
        import funoos_app as fa
        saved = fa.render.save_mp4
        got = {}
        fa.render.save_mp4 = lambda frames, path, fps=26: got.update(n=sum(1 for _ in frames), fps=fps) or Path(path).write_bytes(b"x")
        try:
            cl = api.save_clip("ex1", "Speed", "Turbo", "mp4", {"fps": 12, "scale": 0.5, "t0": 0.5, "t1": 1.0})
        finally:
            fa.render.save_mp4 = saved
        assert cl["ok"] and cl["frames"] == 2 and got == {"n": 2, "fps": 12}
        assert api.save_png("nope", "Speed")["ok"] is False


def test_every_api_response_is_strict_json():
    """Sweeps with unavailable metrics (NaN) and every other reply must be valid JSON (NaN→null)."""
    import json
    api = _api()
    orig = funoos_app.postproc.metrics
    funoos_app.postproc.metrics = lambda res: {"strouhal": float("nan"), "cd": 1.5}
    try:
        r = api.sweep("__quick__", {}, "a", [1, 2], None, None, "nanj")
    finally:
        funoos_app.postproc.metrics = orig
    txt = json.dumps(r, allow_nan=False)                      # raises on NaN
    assert r["items"][0]["metrics"]["strouhal"] is None and r["items"][0]["metrics"]["cd"] == 1.5
    for resp in (api.run("__quick__", {}, None, None, 26, "j1"), api.runs(), api.jobs(), api.job("j1"),
                 api.estimate("Wind Tunnel", {}), api.derived("Rayleigh-Benard", {"kappa": 0}),
                 api.render_view("j1", "Speed", "Turbo", 26, req=1), api.probe("j1", "Speed", 0.03, 0.5, req=2),
                 api.exhibits(), api.catalog(), api.scene_detail("lbm_cylinder"), api.validate("Wind Tunnel", {"reynolds": "x"})):
        json.dumps(resp, allow_nan=False)


def test_derived_readouts_never_fail_a_run():
    """A completed run stays completed even when a derived readout cannot be computed."""
    from flowzoo import schema, catalog
    for s in catalog.SCENES:
        d = schema.derived(s["exhibit"], s["preset"])
        assert d and not d[0]["label"].startswith("derived quantities unavailable"), s["key"]
    d = schema.derived("Rayleigh-Benard", {"kappa": 0})
    assert any("undefined" in x["value"] for x in d if "Prandtl" in x["label"])
    d = schema.derived("The Big Splash", {"scene": "Still water (hydrostatic)"})
    assert any("particles" in x["label"] for x in d)
    api = _api()
    orig = funoos_app.schema.derived
    funoos_app.schema.derived = lambda ex, p: (_ for _ in ()).throw(RuntimeError("readout bug"))
    try:
        r = api.run("__quick__", {}, None, None, 26, "dr1")
    finally:
        funoos_app.schema.derived = orig
    assert r["ok"] and r["state"] == "completed" or api.job("dr1")["state"] == "completed", "the run's terminal state is completed"


def test_probe_export_uses_the_displayed_cell():
    api = _api(); api.run("__quick__", {}, None, None, 26, "pe")
    pr = api.probe("pe", "Speed", 0.03, 0.62, req=1)
    with tempfile.TemporaryDirectory() as d:
        api._win = _FakeWin(d)
        c = api.export_csv("pe", "probe", {"view": "Speed", "ix": pr["ix"], "iy": pr["iy"]})
        head = Path(c["path"]).read_text().splitlines()[0]
        assert f"cell ({pr['ix']}, {pr['iy']})" in head, head
        lp = api.line_profile("pe", "Speed", "x", 0.62, 0.5, req=2)
        c2 = api.export_csv("pe", "profile", {"view": "Speed", "axis": "x", "index": lp["index"], "iy": lp["iy"]})
        h2 = Path(c2["path"]).read_text().splitlines()[0]
        assert f"frame {lp['index']}" in h2 and f"time {lp['time']}" in h2, h2
        rows = Path(c2["path"]).read_text().splitlines()[2:]
        assert len(rows) == 8 and abs(float(rows[3].split(",")[1]) - lp["values"][3]) < 1e-12


def test_compare_requires_compatibility_and_uses_shared_interval():
    api = Api(store=RunStore(max_runs=6, max_bytes=10 ** 9), sweep=False)
    a = api.run("__quick__", {"a": 1}, None, None, 26, "sa"); assert a["ok"]
    # a second result with a longer, offset time axis: shared interval is [1, 2]
    yy, xx = np.mgrid[0:8, 0:8]
    long = engine.Result("lbm", [(np.sin(xx / 3.0 + 0.1 * i).astype(np.float32), np.cos(yy / 3.0).astype(np.float32)) for i in range(5)],
                         "long", hints={"dx": 1.0}, times=[1.0, 1.5, 2.0, 3.0, 4.0])
    api.store.add("sb", long)
    n0 = len(_ENCODES)
    c = api.compare("sa", "sb", "Speed", "Turbo", 26, req=1)
    assert c["ok"] and c["times"] == [1.0, 1.5, 2.0] and _ENCODES[-1] == 3, c.get("times")
    assert "shared interval [1, 2]" in c["note"] and "not shown" in c["note"] and c["vmin"] is not None
    other = engine.Result("field", [np.random.rand(8, 8) for _ in range(3)], "field", hints={"label": "dye"}, times=[0.0, 1.0, 2.0])
    api.store.add("sc", other)
    r = api.compare("sa", "sc", "Speed"); assert r["ok"] is False and r.get("incompatible") and "families" in r["error"]
    units = engine.Result("lbm", long.raw, "u", hints={"dx": 1.0, "time_unit": "s"}, times=[1.0, 1.5, 2.0, 3.0, 4.0])
    api.store.add("sd", units)
    r = api.compare("sa", "sd", "Speed"); assert r["ok"] is False and "time units" in r["error"]


def test_sweep_children_are_jobs_and_are_retained():
    api = Api(store=RunStore(max_runs=2, max_bytes=10 ** 9), sweep=False)      # store smaller than the sweep
    r = api.sweep("__quick__", {}, "a", [1, 2, 3, 4, 5], None, None, "swj")
    assert r["ok"] and len(r["items"]) == 5 and all(r["retained"]), "all five children kept"
    for k, it in enumerate(r["items"]):
        j = api.job(it["run_id"])
        assert j["ok"] and j["state"] == "completed" and j["params"]["a"] == k + 1 and j["parent"] == "swj"
        assert j["provenance"]["solver_versions"] and j["provenance"]["started"]
    rec = api.project(None, "__quick__", {"a": 99}, None, None, False, r["items"][2]["run_id"])
    assert rec["schema_version"] == 2 and rec["run"]["params"]["a"] == 3 and rec["params"]["a"] == 99
    assert rec["draft_matches_run"] is False and rec["run"]["provenance"]["solver_versions"]
    rec2 = api.project(None, "__quick__", {"a": 3}, None, None, False, r["items"][2]["run_id"])
    assert rec2["draft_matches_run"] is True


def test_provenance_frozen_at_start():
    api = _api(); r = api.run("__quick__", {}, None, None, 26, "prov"); assert r["ok"]
    before = api.job("prov")["provenance"]
    orig = engine.solver_versions; engine.solver_versions = lambda: {"lbm2d": {"source_sha256": "changed"}}
    try:
        assert api.job("prov")["provenance"] == before, "recorded at start, not reconstructed later"
        rec = api.project(None, "__quick__", {}, None, None, False, "prov")
        assert rec["run"]["provenance"] == before
    finally:
        engine.solver_versions = orig


# ----------------------------------------------------------------- result store
def test_store_bounded_by_count_lru():
    st = RunStore(max_runs=3, max_bytes=10 ** 9)
    for i in range(5):
        st.add(f"r{i}", FakeResult())
    assert st.ids() == ["r2", "r3", "r4"]
    st.get("r2")                                         # touch -> most recently used
    time.sleep(0.01); st.add("r5", FakeResult())
    assert st.ids() == ["r2", "r4", "r5"], st.ids()      # r3 (least recently used) evicted, not r2


def test_store_bounded_by_bytes_and_pinning():
    one = result_bytes(FakeResult(nframes=4))
    st = RunStore(max_runs=10, max_bytes=int(2.5 * one))
    st.add("a", FakeResult(4)); st.add("b", FakeResult(4))
    assert st.ids() == ["a", "b"] and st.total_bytes() == 2 * one
    ev = st.add("c", FakeResult(4))
    assert ev == ["a"] and st.ids() == ["b", "c"]
    assert st.pin("b")
    ev = st.add("d", FakeResult(4))
    assert ev == ["c"] and st.ids() == ["b", "d"], "pinned run survives, LRU unpinned goes"
    ev = st.add("e", FakeResult(4))
    assert ev == ["d"] and st.ids() == ["b", "e"]
    st.pin("e")
    ev = st.add("big", FakeResult(40))                   # over budget but nothing evictable
    assert ev == [] and st.ids() == ["b", "e", "big"]
    assert st.total_bytes() > st.max_bytes
    st.pin("b", False)
    assert st.evict() == ["b", "big"], "re-evaluating the budget drops LRU unpinned runs until it fits"
    assert st.pin("nope") is False


def test_api_store_integration_and_budget():
    api = Api(store=RunStore(max_runs=2, max_bytes=10 ** 9), sweep=False)
    for i in range(3):
        r = api.run("__quick__", {}, None, None, 26, f"s{i}")
    assert r["evicted"] == ["s0"] and r["store"]["runs"] == 2
    assert api.pin_run("s1")["ok"] and api.runs()["runs"][0]["pinned"]
    b = api.set_budget(max_runs=1)
    assert b["evicted"] == ["s2"] and [x["run_id"] for x in b["runs"]] == ["s1"]
    assert api.pin_run("gone")["ok"] is False


def test_large_results_spill_to_disk_and_clean_up():
    """Results above the spill threshold are memory-mapped from a scratch directory that
    is removed on eviction; they still render, and RAM accounting drops accordingly."""
    with tempfile.TemporaryDirectory() as d:
        st = RunStore(max_runs=2, max_bytes=10 ** 9, spill_bytes=1000, spill_dir=d)
        big = FakeResult(nframes=6, tag="big")
        st.add("big", big)
        e = st.get("big")
        assert e["disk"] > 0 and e["bytes"] == 0 and big.hints["spilled_to"].startswith(d)
        assert type(big.raw[0][0]).__name__ == "memmap"
        assert len(big.render("Speed")) == 6, "renders from the memory-mapped arrays"
        assert st.disk_total() == e["disk"]
        st.add("b", FakeResult(2)); st.add("c", FakeResult(2))
        assert "big" not in st and not Path(big.hints["spilled_to"]).exists(), "spill directory removed on eviction"
        st.clear()
        assert not any(Path(d).iterdir()), "clear() removes every spill directory"
        # a disk budget also evicts
        st2 = RunStore(max_runs=10, max_bytes=10 ** 9, spill_bytes=1000, disk_bytes=result_bytes(FakeResult(6)) + 10, spill_dir=d)
        st2.add("x", FakeResult(6)); ev = st2.add("y", FakeResult(6))
        assert ev == ["x"] and st2.ids() == ["y"]


def test_shutdown_kills_live_solver():
    api = _api()
    th = threading.Thread(target=lambda: api.run("__subproc__", {}, None, None, 26, "sd"))
    th.start(); time.sleep(0.6)
    assert engine._LIVE_PROCS, "solver running"
    s = api.shutdown()
    th.join(timeout=5)
    assert not th.is_alive() and not engine._LIVE_PROCS and s["ok"]
    assert api.job("sd")["state"] == "cancelled" and len(api.store) == 0


# ----------------------------------------------------------------- crash cleanup
def test_sweep_stale_temp():
    with tempfile.TemporaryDirectory() as base:
        b = Path(base)
        dead = b / "funoos-999999999-abc"; dead.mkdir(); (dead / "x.bin").write_bytes(b"1")
        mine = b / f"funoos-{os.getpid()}-def"; mine.mkdir()
        other = b / "funoos-notapid"; other.mkdir()
        removed = sweep_stale_temp(b)
        assert removed == [str(dead)]
        assert not dead.exists() and mine.exists() and other.exists()
    # the engine's scratch dirs use the sweepable prefix and are removed after a solve
    seen = []
    def solve(p, pr, tmp): seen.append(tmp); return FakeResult()
    engine.EXHIBITS["__tmp__"] = {"params": [], "solve": solve}
    engine.solve_exhibit("__tmp__", {})
    assert Path(seen[0]).name.startswith(f"funoos-{os.getpid()}-") and not Path(seen[0]).exists()


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
