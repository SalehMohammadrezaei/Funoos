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


class FakeResult:
    """Minimal engine.Result look-alike (kind lbm so views/colormaps resolve)."""
    kind = "lbm"

    def __init__(self, nframes=3, tag="fake"):
        self.raw = [np.zeros((8, 8), np.float32) for _ in range(nframes)]
        self.mask, self.hints, self.info = None, {}, f"{tag}  8×8"

    @property
    def views(self):
        return engine.VIEWS[self.kind]

    def render(self, view=None, colormap=None):
        return [np.zeros((8, 8, 3), np.uint8) for _ in self.raw]


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
funoos_app._b64_mp4 = lambda frames, fps: "data:video/mp4;base64,AAAA"   # no ffmpeg needed


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
