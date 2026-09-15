"""Funoos — desktop app (pywebview shell around the HTML/CSS/JS UI).

The C++/Python solvers are unchanged; this only swaps the presentation layer.
`Api` is the bridge the web UI calls (pywebview.api.*): it lists the catalog,
serves parameter specs + write-ups, and — on Run — solves once and encodes the
chosen view to an MP4 returned as a base64 data-URL (so there's no file server
to manage). Results are kept in a bounded store so view-switching and the
diagnostics plots are instant without memory growing run after run.

Job lifecycle
-------------
Every Run is a `Job` with an immutable parameter snapshot and an explicit state
(preparing → running → rendering → completed | cancelled | failed). `cancel()`
sets the job's event: C++ solvers are killed by the engine, in-process solvers
stop at their next progress report. Progress events carry the job id so the UI
can attach them to the right job. Every API call that can fail returns a plain
envelope — `{"ok": True, ...}` or `{"ok": False, "error": "..."}` — never an
exception the frontend might mistake for a result. Requests that the UI issues
concurrently (render/detail/diagnostics) carry a `req` token that is echoed
back so stale responses can be discarded.

Result storage
--------------
`RunStore` keeps at most `FUNOOS_MAX_RUNS` results and at most `FUNOOS_MEMORY_MB`
of raw field data; the least recently used unpinned run is evicted first.
Pinned runs are never evicted. The video the UI is playing is a data URL held
by the browser, so eviction never interrupts playback — it only disables view
switching / diagnostics for that run ("run expired").

    pip install pywebview
    python funoos_app.py
"""
from __future__ import annotations

import base64
import copy
import io
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types
import uuid
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render, content, postproc, catalog   # noqa: E402

# ---------------------------------------------------------------- result storage
MAX_RUNS = int(os.environ.get("FUNOOS_MAX_RUNS", "3"))
MEMORY_BUDGET_MB = float(os.environ.get("FUNOOS_MEMORY_MB", "1024"))
MAX_JOB_RECORDS = 30           # finished job records kept for state queries


def result_bytes(obj):
    """Bytes of numpy data reachable from `obj` (lists/tuples/dicts of arrays)."""
    import numpy as np
    if isinstance(obj, np.ndarray):
        return int(obj.nbytes)
    if isinstance(obj, dict):
        return sum(result_bytes(v) for v in obj.values())
    if isinstance(obj, (list, tuple)):
        return sum(result_bytes(v) for v in obj)
    raw = getattr(obj, "raw", None)
    if raw is not None:                      # engine.Result
        return result_bytes(raw) + result_bytes(getattr(obj, "mask", None)) \
            + result_bytes(getattr(obj, "hints", None))
    return 0


class RunStore:
    """Bounded, pinnable store of completed results (LRU eviction of unpinned runs).

    Limits: at most `max_runs` entries and at most `max_bytes` of raw field data.
    The entry being added is never evicted (a single run larger than the budget
    is kept and reported), pinned entries are never evicted, and eviction order
    is least-recently-used first — so a run the user keeps switching views on is
    the last to go.
    """

    def __init__(self, max_runs=MAX_RUNS, max_bytes=int(MEMORY_BUDGET_MB * 2 ** 20)):
        self.max_runs = max(1, int(max_runs))
        self.max_bytes = max(0, int(max_bytes))
        self._runs = {}
        self._lock = threading.Lock()

    def add(self, run_id, result, info=None, pinned=False):
        with self._lock:
            now = time.time()
            self._runs[run_id] = {"result": result, "info": info or getattr(result, "info", ""),
                                  "bytes": result_bytes(result), "pinned": bool(pinned),
                                  "created": now, "last_used": now}
            return self._evict(keep=run_id)

    def get(self, run_id, touch=True):
        with self._lock:
            r = self._runs.get(run_id)
            if r and touch:
                r["last_used"] = time.time()
            return r

    def result(self, run_id):
        r = self.get(run_id)
        return r["result"] if r else None

    def pin(self, run_id, pinned=True):
        with self._lock:
            r = self._runs.get(run_id)
            if not r:
                return False
            r["pinned"] = bool(pinned)
            return True

    def remove(self, run_id):
        with self._lock:
            return self._runs.pop(run_id, None) is not None

    def clear(self):
        with self._lock:
            self._runs.clear()

    def set_limits(self, max_runs=None, max_bytes=None):
        with self._lock:
            if max_runs is not None:
                self.max_runs = max(1, int(max_runs))
            if max_bytes is not None:
                self.max_bytes = max(0, int(max_bytes))
            return self._evict()

    def evict(self, keep=None):
        with self._lock:
            return self._evict(keep)

    def _evict(self, keep=None):
        evicted = []
        while len(self._runs) > self.max_runs or self.total_bytes() > self.max_bytes:
            cands = [(r["last_used"], rid) for rid, r in self._runs.items()
                     if not r["pinned"] and rid != keep]
            if not cands:
                break                                   # nothing evictable: over budget but pinned/current
            _, victim = min(cands)
            del self._runs[victim]; evicted.append(victim)
        return evicted

    def total_bytes(self):
        return sum(r["bytes"] for r in self._runs.values())

    def ids(self):
        return list(self._runs)

    def summary(self):
        with self._lock:
            return [{"run_id": rid, "info": r["info"], "pinned": r["pinned"],
                     "bytes": r["bytes"], "created": r["created"], "last_used": r["last_used"]}
                    for rid, r in self._runs.items()]

    def __len__(self):
        return len(self._runs)

    def __contains__(self, run_id):
        return run_id in self._runs


# ---------------------------------------------------------------- jobs
STATES = ("preparing", "running", "rendering", "completed", "cancelled", "failed")
ACTIVE_STATES = ("preparing", "running", "rendering")
_ID_RE = re.compile(r"[A-Za-z0-9_-]{1,40}")


class Job:
    """One simulation request: immutable parameter snapshot + explicit state machine."""

    def __init__(self, job_id, exhibit, params, view=None, cmap=None):
        self.id = job_id
        self.exhibit = exhibit
        self._params = copy.deepcopy(dict(params or {}))
        self.params = types.MappingProxyType(self._params)      # read-only snapshot
        self.view, self.cmap = view, cmap
        self.state = "preparing"
        self.error = None
        self.run_id = None
        self.cancel = threading.Event()
        self.created = time.time()
        self.history = [("preparing", self.created)]

    def set_state(self, state):
        if state not in STATES:
            raise ValueError(state)
        self.state = state
        self.history.append((state, time.time()))

    @property
    def active(self):
        return self.state in ACTIVE_STATES

    def snapshot(self):
        return {"job_id": self.id, "exhibit": self.exhibit, "params": dict(self._params),
                "state": self.state, "error": self.error, "run_id": self.run_id,
                "cancel_requested": self.cancel.is_set(), "created": self.created,
                "history": [{"state": s, "t": t} for s, t in self.history]}


def _errtext(e):
    """Human-readable, single-line error text for the UI (never an empty string)."""
    import subprocess
    if isinstance(e, subprocess.CalledProcessError):
        return f"solver exited with code {e.returncode}"
    msg = str(e).strip().splitlines()[0] if str(e).strip() else ""
    return f"{type(e).__name__}: {msg}" if msg else type(e).__name__


# ---------------------------------------------------------------- crash cleanup
def _pid_alive(pid):
    if pid == os.getpid():
        return True
    if sys.platform.startswith("win"):
        import ctypes
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(0x1000, False, int(pid))         # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code)); k32.CloseHandle(h)
        return bool(ok) and code.value == 259                # STILL_ACTIVE
    try:
        os.kill(int(pid), 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def sweep_stale_temp(tmpdir=None):
    """Remove solver scratch dirs (`funoos-<pid>-*`) left behind by Funoos processes
    that no longer exist — i.e. clean up after a crash at the next launch."""
    base = Path(tmpdir or tempfile.gettempdir())
    removed = []
    for d in base.glob("funoos-*-*"):
        m = re.match(r"funoos-(\d+)-", d.name)
        if not m or not d.is_dir() or _pid_alive(int(m.group(1))):
            continue
        shutil.rmtree(d, ignore_errors=True)
        removed.append(str(d))
    return removed


# ---------------------------------------------------------------- helpers
def _b64_png(rgb):
    from PIL import Image
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _b64_mp4(frames, fps):
    with tempfile.TemporaryDirectory(prefix=engine.TMP_PREFIX) as d:
        p = Path(d) / "v.mp4"; render.save_mp4(frames, p, fps=fps)
        data = p.read_bytes()
    return "data:video/mp4;base64," + base64.b64encode(data).decode()


def _param_spec(exhibit):
    """JSON-safe parameter descriptors (drops the solve lambda; keeps `when`)."""
    out = []
    for qd in engine.EXHIBITS[exhibit]["params"]:
        q = {k: v for k, v in qd.items() if k != "solve"}
        if "when" in q:                       # tuple -> list for JSON
            q["when"] = [q["when"][0], list(q["when"][1])]
        out.append(q)
    return out


def _eq_b64(exhibit):
    slug = "".join(c if c.isalnum() else "_" for c in exhibit).strip("_").lower()
    p = ROOT / "docs" / "eq" / (slug + ".png")
    if p.exists():
        return "data:image/png;base64," + base64.b64encode(p.read_bytes()).decode()
    return None


def _stats(res, exhibit):
    """Live KPI readouts for the Studio dashboard tiles."""
    h = res.hints
    meth = engine.META.get(exhibit, {}).get("method", "").split("·")[0].strip()
    out = []
    if res.kind == "porous":
        k_val = h.get("permeability", 0); phi = h.get("porosity", 0)
        out.append({"l": "permeability k", "v": f"{k_val:.2f}", "u": "cells²", "accent": True,
                    "frac": float(min(1.0, k_val / 20.0))})
        out.append({"l": "porosity φ", "v": f"{phi:.2f}", "frac": float(min(1.0, max(0.0, phi)))})
    out.append({"l": "frames", "v": str(len(res.raw))})
    out.append({"l": "views", "v": str(len(res.views))})
    out.append({"l": "method", "v": meth})
    return out


def _js(s):
    return json.dumps(s)


class Api:
    def __init__(self, store=None, sweep=True):
        self.store = store if store is not None else RunStore()   # (an empty store is falsy)
        self._jobs = {}                  # job_id -> Job (insertion ordered)
        self._lock = threading.Lock()
        self._win = None
        self.swept = sweep_stale_temp() if sweep else []

    # ---------- static content ----------
    def catalog(self):
        groups = []
        for method, scenes in catalog.by_method().items():
            items = []
            for s in scenes:
                key = s["key"]
                mp4 = ROOT / "results" / "gallery" / (key + ".mp4")
                items.append({"key": key, "name": s["name"], "blurb": s["blurb"],
                              "exhibit": s["exhibit"], "preset": s["preset"],
                              "clip": ("results/gallery/" + key + ".mp4") if mp4.exists() else None})
            groups.append({"method": method, "scenes": items})
        return groups

    def scene_detail(self, key, req=None):
        s = catalog.scene(key)
        if not s:
            return {"ok": False, "error": f"unknown scene: {key}", "req": req}
        ex = s["exhibit"]; m = engine.META.get(ex, {}); d = content.DETAIL.get(ex, {})
        setup = content.SETUP.get(ex, {})
        return {"ok": True, "req": req, "key": key,
                "name": s["name"], "method": s["method"], "exhibit": ex,
                "blurb": s["blurb"], "physics": d.get("physics", m.get("blurb", "")),
                "terms": d.get("terms", ""), "numerics": m.get("numerics", ""),
                "ic": setup.get("ic", ""), "bc": setup.get("bc", ""),
                "validation": m.get("validation", ""), "eq": _eq_b64(ex),
                "clip": "results/gallery/" + key + ".mp4", "preset": s["preset"],
                "cmap": s.get("cmap"), "params": _param_spec(ex), "method_label": m.get("method", "")}

    # ---------- job registry ----------
    def _new_job(self, exhibit, params, view, cmap, job_id=None):
        with self._lock:
            jid = job_id if (isinstance(job_id, str) and _ID_RE.fullmatch(job_id)
                             and job_id not in self._jobs) else uuid.uuid4().hex[:12]
            job = Job(jid, exhibit, params, view, cmap)
            # one worker at a time: a new Run supersedes anything still in flight
            for other in self._jobs.values():
                if other.active:
                    other.cancel.set()
            self._jobs[jid] = job
            finished = [k for k, j in self._jobs.items() if not j.active]
            for k in finished[:-MAX_JOB_RECORDS] if len(finished) > MAX_JOB_RECORDS else []:
                del self._jobs[k]
            return job

    def _emit_progress(self, job_id, msg):
        if self._win:
            try:
                self._win.evaluate_js(
                    f"window.onProgress && window.onProgress({_js(msg)}, {_js(job_id)})")
            except Exception:
                pass

    def cancel(self, job_id):
        """Request cancellation; the solver is killed / stopped at its next progress tick."""
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"ok": False, "job_id": job_id, "error": "unknown job"}
        if job.active:
            job.cancel.set()
        return {"ok": True, "job_id": job_id, "state": job.state, "cancel_requested": job.cancel.is_set()}

    def cancel_all(self):
        with self._lock:
            jobs = [j for j in self._jobs.values() if j.active]
        for j in jobs:
            j.cancel.set()
        return {"ok": True, "cancelled": [j.id for j in jobs]}

    def job(self, job_id):
        with self._lock:
            job = self._jobs.get(job_id)
        if not job:
            return {"ok": False, "job_id": job_id, "error": "unknown job"}
        return {"ok": True, **job.snapshot()}

    def jobs(self):
        with self._lock:
            return {"ok": True, "jobs": [j.snapshot() for j in self._jobs.values()]}

    # ---------- run / render ----------
    def run(self, exhibit, params, view=None, cmap=None, fps=26, job_id=None):
        """Solve + render. Blocks until the job reaches a terminal state and returns
        its envelope; call `cancel(job_id)` from another thread to stop it."""
        job = self._new_job(exhibit, params, view, cmap, job_id)
        progress = lambda msg: self._emit_progress(job.id, msg)   # noqa: E731
        try:
            if exhibit not in engine.EXHIBITS:
                raise KeyError(f"unknown exhibit: {exhibit}")
            job.set_state("running")
            res = engine.solve_exhibit(job.exhibit, dict(job.params), progress=progress,
                                       cancel=job.cancel)
            if job.cancel.is_set():
                raise engine.Cancelled()
            job.set_state("rendering")
            view = view if view in res.views else res.views[0]
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            progress(f"rendering {view}…")
            vid = _b64_mp4(res.render(view, cm), fps)
            if job.cancel.is_set():
                raise engine.Cancelled()
            evicted = self.store.add(job.id, res, res.info)
            job.run_id = job.id
            job.set_state("completed")
            return {"ok": True, "job_id": job.id, "run_id": job.id, "state": "completed",
                    "video": vid, "views": list(res.views), "view": view, "info": res.info,
                    "cmaps": list(render.COLORMAPS), "defcmap": cm, "stats": _stats(res, exhibit),
                    "params": dict(job.params), "evicted": evicted,
                    "store": {"runs": len(self.store), "bytes": self.store.total_bytes()}}
        except engine.Cancelled:
            job.set_state("cancelled"); job.error = "cancelled"
            return {"ok": False, "job_id": job.id, "state": "cancelled", "error": "cancelled"}
        except Exception as e:                      # noqa: BLE001 — every failure becomes a plain envelope
            job.error = _errtext(e)
            job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error}

    def render_view(self, run_id, view, cmap=None, fps=26, req=None):
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id, "req": req}
        try:
            view = view if view in res.views else res.views[0]
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            return {"ok": True, "run_id": run_id, "req": req, "view": view, "cmap": cm,
                    "video": _b64_mp4(res.render(view, cm), fps)}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id, "req": req}

    def save_clip(self, run_id, view, cmap=None, fmt="mp4"):
        """Render the current view and save it to a user-chosen file (MP4 or GIF).
        `path` is None when the user dismissed the dialog."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id}
        if not self._win:
            return {"ok": False, "error": "no window", "run_id": run_id}
        try:
            import webview
            view = view if view in res.views else res.views[0]
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            fmt = "gif" if str(fmt).lower() == "gif" else "mp4"
            name = "".join(c if c.isalnum() else "_" for c in res.info.split("·")[0]).strip("_")[:40] or "funoos"
            sel = self._win.create_file_dialog(
                webview.SAVE_DIALOG, save_filename=f"{name}.{fmt}",
                file_types=(f"{fmt.upper()} (*.{fmt})", "All files (*.*)"))
            if not sel:
                return {"ok": True, "path": None, "run_id": run_id}
            path = sel[0] if isinstance(sel, (list, tuple)) else sel
            if not path.lower().endswith("." + fmt):
                path += "." + fmt
            frames = res.render(view, cm)
            (render.save_gif if fmt == "gif" else render.save_mp4)(frames, path, fps=26)
            return {"ok": True, "path": path, "run_id": run_id}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id}

    def diagnostics(self, run_id, req=None):
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id, "req": req}
        try:
            plots = [{"title": t, "img": _b64_png(img), "explain": ex}
                     for t, img, ex in postproc.plots(res)]
            return {"ok": True, "run_id": run_id, "req": req, "plots": plots}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id, "req": req}

    # ---------- result store ----------
    def runs(self):
        return {"ok": True, "runs": self.store.summary(), "max_runs": self.store.max_runs,
                "max_bytes": self.store.max_bytes, "bytes": self.store.total_bytes()}

    def pin_run(self, run_id, pinned=True):
        if not self.store.pin(run_id, pinned):
            return {"ok": False, "error": "run expired", "run_id": run_id}
        return {"ok": True, "run_id": run_id, "pinned": bool(pinned)}

    def set_budget(self, max_runs=None, memory_mb=None):
        evicted = self.store.set_limits(max_runs, None if memory_mb is None else float(memory_mb) * 2 ** 20)
        return {"ok": True, "evicted": evicted, **self.runs()}

    # ---------- lifecycle ----------
    def shutdown(self):
        """Stop every active job and kill live solver processes (window close / exit)."""
        self.cancel_all()
        killed = engine.kill_all_solvers()
        self.store.clear()
        return {"ok": True, "killed": killed}


def main():
    try:
        import webview
    except Exception:
        print("pywebview not installed.  pip install pywebview\n"
              "(then: python funoos_app.py)")
        return
    import atexit
    api = Api()
    win = webview.create_window("Funoos — where imagination becomes vision",
                                str(ROOT / "index.html"), js_api=api,
                                width=1440, height=900, min_size=(1120, 720),
                                background_color="#0A1322")
    api._win = win
    def on_close():                                              # stop solvers when the window closes
        api.shutdown()
    win.events.closing += on_close
    atexit.register(api.shutdown)
    webview.start(http_server=True)


if __name__ == "__main__":
    main()
