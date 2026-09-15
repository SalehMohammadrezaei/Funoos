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
from flowzoo import engine, render, content, postproc, catalog, schema, analysis   # noqa: E402
try:
    from flowzoo import __version__ as APP_VERSION
except Exception:                                          # noqa: BLE001
    APP_VERSION = "dev"

# ---------------------------------------------------------------- result storage
MAX_RUNS = int(os.environ.get("FUNOOS_MAX_RUNS", "3"))
MEMORY_BUDGET_MB = float(os.environ.get("FUNOOS_MEMORY_MB", "1024"))
DISK_SPILL_MB = float(os.environ.get("FUNOOS_DISK_SPILL_MB", "256"))   # results above this are memory-mapped from disk
DISK_BUDGET_MB = float(os.environ.get("FUNOOS_DISK_MB", "4096"))       # cap on spilled data kept on disk
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

    def __init__(self, max_runs=MAX_RUNS, max_bytes=int(MEMORY_BUDGET_MB * 2 ** 20),
                 spill_bytes=int(DISK_SPILL_MB * 2 ** 20), disk_bytes=int(DISK_BUDGET_MB * 2 ** 20),
                 spill_dir=None):
        self.max_runs = max(1, int(max_runs))
        self.max_bytes = max(0, int(max_bytes))
        self.spill_bytes = int(spill_bytes) if spill_bytes else None     # None: never spill
        self.disk_bytes = max(0, int(disk_bytes))
        self.spill_dir = Path(spill_dir) if spill_dir else Path(tempfile.gettempdir())
        self._runs = {}
        self._lock = threading.Lock()

    def add(self, run_id, result, info=None, pinned=False):
        nbytes = result_bytes(result); on_disk = 0
        if self.spill_bytes and nbytes > self.spill_bytes and hasattr(result, "spill"):
            d = self.spill_dir / f"{engine.TMP_PREFIX}run-{run_id}"          # swept at next launch after a crash
            try:
                on_disk = result.spill(d); nbytes = result_bytes(result) - on_disk
            except Exception:
                on_disk = 0; shutil.rmtree(d, ignore_errors=True)
        with self._lock:
            now = time.time()
            self._runs[run_id] = {"result": result, "info": info or getattr(result, "info", ""),
                                  "bytes": max(0, nbytes), "disk": on_disk, "pinned": bool(pinned),
                                  "created": now, "last_used": now}
            return self._evict(keep=run_id)

    def _release(self, rid):
        r = self._runs.pop(rid)
        d = getattr(r["result"], "hints", {}).get("spilled_to") if r.get("disk") else None
        if d:
            try:
                r["result"].raw = []; r["result"].hints.pop("vel", None); r["result"]._cache.clear()
            except Exception:
                pass
            shutil.rmtree(d, ignore_errors=True)

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
            if run_id not in self._runs:
                return False
            self._release(run_id); return True

    def clear(self):
        with self._lock:
            for rid in list(self._runs):
                self._release(rid)

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
        while (len(self._runs) > self.max_runs or self.total_bytes() > self.max_bytes
               or self.disk_total() > self.disk_bytes):
            cands = [(r["last_used"], rid) for rid, r in self._runs.items()
                     if not r["pinned"] and rid != keep]
            if not cands:
                break                                   # nothing evictable: over budget but pinned/current
            _, victim = min(cands)
            self._release(victim); evicted.append(victim)
        return evicted

    def total_bytes(self):
        return sum(r["bytes"] for r in self._runs.values())

    def disk_total(self):
        return sum(r.get("disk", 0) for r in self._runs.values())

    def ids(self):
        return list(self._runs)

    def summary(self):
        with self._lock:
            return [{"run_id": rid, "info": r["info"], "pinned": r["pinned"],
                     "bytes": r["bytes"], "disk": r.get("disk", 0), "created": r["created"], "last_used": r["last_used"]}
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
    """Encode an iterable of frames (list or generator) and return a data URL."""
    with tempfile.TemporaryDirectory(prefix=engine.TMP_PREFIX) as d:
        p = Path(d) / "v.mp4"; render.save_mp4(frames, p, fps=fps)
        data = p.read_bytes()
    return "data:video/mp4;base64," + base64.b64encode(data).decode()


class _Superseded(Exception):
    """A newer request for the same run replaced this one while it was encoding."""


MAX_VIEW_CACHE = int(os.environ.get("FUNOOS_VIEW_CACHE", "12"))   # rendered clips kept (all runs)


class ViewCache:
    """LRU cache of encoded clips keyed by (run_id, view, cmap, fps, vmin, vmax)."""

    def __init__(self, max_items=MAX_VIEW_CACHE):
        self.max_items = max(1, int(max_items)); self._d = {}; self._lock = threading.Lock()

    def get(self, key):
        with self._lock:
            v = self._d.pop(key, None)
            if v is not None:
                self._d[key] = v                 # most recently used
            return v

    def put(self, key, value):
        with self._lock:
            self._d[key] = value
            while len(self._d) > self.max_items:
                del self._d[next(iter(self._d))]

    def drop_run(self, run_id):
        with self._lock:
            for k in [k for k in self._d if k[0] == run_id]:
                del self._d[k]

    def __len__(self):
        return len(self._d)


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
        self.views = ViewCache()
        self._jobs = {}                  # job_id -> Job (insertion ordered)
        self._lock = threading.Lock()
        self._encode = threading.Lock()  # one expensive encode at a time (bounded worker)
        self._latest = {}                # run_id -> newest render request token seen
        self._win = None
        self.swept = sweep_stale_temp() if sweep else []

    # ---------- static content ----------
    def catalog(self):
        """Scenes grouped by phenomenon (the gallery's organisation), with method/status/question."""
        groups = []
        for phen, scenes in catalog.by_phenomenon().items():
            items = []
            for s in scenes:
                key = s["key"]
                mp4 = ROOT / "results" / "gallery" / (key + ".mp4")
                items.append({"key": key, "name": s["name"], "blurb": s["blurb"], "method": s["method"],
                              "exhibit": s["exhibit"], "preset": s["preset"], "question": s["question"],
                              "status": s["status"], "status_label": catalog.STATUS_LABEL[s["status"]],
                              "estimate_s": engine.estimate(s["exhibit"], s["preset"]).get("seconds"),
                              "clip": ("results/gallery/" + key + ".mp4") if mp4.exists() else None})
            groups.append({"phenomenon": phen, "scenes": items})
        return {"ok": True, "groups": groups, "methods": sorted({s["method"] for s in catalog.SCENES}),
                "counts": catalog.counts()}

    def scene_detail(self, key, req=None):
        s = catalog.scene(key)
        if not s:
            return {"ok": False, "error": f"unknown scene: {key}", "req": req}
        ex = s["exhibit"]; m = engine.META.get(ex, {}); d = content.DETAIL.get(ex, {})
        setup = content.SETUP.get(ex, {})
        return {"ok": True, "req": req, "key": key,
                "name": s["name"], "method": s["method"], "exhibit": ex, "phenomenon": s["phenomenon"],
                "question": s["question"], "status": s["status"], "status_label": catalog.STATUS_LABEL[s["status"]],
                "blurb": s["blurb"], "physics": d.get("physics", m.get("blurb", "")),
                "terms": d.get("terms", ""), "numerics": m.get("numerics", ""),
                "ic": setup.get("ic", ""), "bc": setup.get("bc", ""),
                "validation": s.get("checks", m.get("validation", "")), "eq": _eq_b64(ex),
                "clip": ("results/gallery/" + key + ".mp4") if (ROOT / "results" / "gallery" / (key + ".mp4")).exists() else None,
                "preset": s["preset"], "layers": catalog.scene_layers(key)["layers"],
                "cmap": s.get("cmap"), "params": _param_spec(ex), "method_label": m.get("method", "")}

    def validate(self, exhibit, params, advanced=False):
        """Validate a setup without running it (errors / warnings / applied adjustments)."""
        try:
            return {"ok": True, "exhibit": exhibit, **schema.validate(exhibit, params or {}, allow_outside=bool(advanced)).as_dict()}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    def derived(self, exhibit, params):
        """Derived quantities the runner will use for this setup."""
        try:
            return {"ok": True, "exhibit": exhibit, "items": schema.derived(exhibit, params or {})}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    def exhibits(self):
        """Every exhibit with its parameter spec (for a scene picker inside the Studio)."""
        return {"ok": True, "exhibits": [{"name": n, "params": _param_spec(n),
                                          "method": engine.META.get(n, {}).get("method", "")}
                                         for n in engine.EXHIBITS]}

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

    def _emit(self, js):
        if self._win:
            try:
                self._win.evaluate_js(js)
            except Exception:
                pass

    def _emit_preview(self, job_id, png, label):
        self._emit(f"window.onPreview && window.onPreview({_js(job_id)}, {_js(png)}, {_js(label)})")

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
    def run(self, exhibit, params, view=None, cmap=None, fps=26, job_id=None, advanced=False):
        """Solve + render. Blocks until the job reaches a terminal state and returns
        its envelope; call `cancel(job_id)` from another thread to stop it.
        Parameters are validated first: an invalid setup fails before any solver starts.
        `advanced=True` allows values outside the recommended (soft) ranges."""
        if exhibit not in engine.EXHIBITS:
            job = self._new_job(exhibit, params, view, cmap, job_id)
            job.error = f"unknown exhibit: {exhibit}"; job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error}
        val = schema.validate(exhibit, params, allow_outside=bool(advanced))
        job = self._new_job(exhibit, val.params, view, cmap, job_id)
        if not val.ok:
            job.error = "invalid setup: " + "; ".join(val.errors); job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error,
                    "validation": val.as_dict()}
        progress = lambda msg: self._emit_progress(job.id, msg)   # noqa: E731
        try:
            job.set_state("running")
            res = engine.solve_exhibit(job.exhibit, dict(job.params), progress=progress,
                                       cancel=job.cancel)
            if job.cancel.is_set():
                raise engine.Cancelled()
            job.set_state("rendering")
            view = res.view_name(view)
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            progress(f"rendering {view}…")
            # show something useful before the clip exists: the final frame as a still
            self._emit_preview(job.id, _b64_png(res.frame(-1, view, cm)), f"{view} · last frame (video encoding…)")
            if job.cancel.is_set():
                raise engine.Cancelled()
            with self._encode:
                vid = _b64_mp4(self._frames(res, view, cm, fps, cancel=job.cancel), fps)
            if job.cancel.is_set():
                raise engine.Cancelled()
            evicted = self.store.add(job.id, res, res.info)
            for rid in evicted:
                self.views.drop_run(rid)
            self.views.put((job.id, view, cm, fps, None, None), vid)
            job.run_id = job.id
            job.set_state("completed")
            return {"ok": True, "job_id": job.id, "run_id": job.id, "state": "completed",
                    "video": vid, "views": list(res.views), "view": view, "info": res.info,
                    "cmaps": list(render.COLORMAPS), "defcmap": cm, "stats": _stats(res, exhibit),
                    "params": dict(job.params), "evicted": evicted, "meta": res.meta(),
                    "validation": val.as_dict(), "derived": schema.derived(exhibit, dict(job.params)),
                    "store": {"runs": len(self.store), "bytes": self.store.total_bytes()}}
        except engine.Cancelled:
            job.set_state("cancelled"); job.error = "cancelled"
            return {"ok": False, "job_id": job.id, "state": "cancelled", "error": "cancelled"}
        except Exception as e:                      # noqa: BLE001 — every failure becomes a plain envelope
            job.error = _errtext(e)
            job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error}

    def _frames(self, res, view, cm, fps, cancel=None, run_id=None, req=None, vmin=None, vmax=None):
        """Frame generator that stops early when its job is cancelled or a newer render
        request for the same run has arrived (so obsolete encodes are abandoned)."""
        for i, fr in enumerate(res.iter_frames(view, cm, vmin, vmax)):
            if cancel is not None and cancel.is_set():
                raise engine.Cancelled()
            if run_id is not None and req is not None and self._latest.get(run_id, req) != req:
                raise _Superseded()
            yield fr

    def render_view(self, run_id, view, cmap=None, fps=26, req=None, vmin=None, vmax=None):
        """Encode a view of a stored run. Cached per (run, view, palette, fps, limits); a
        request superseded by a newer one for the same run is abandoned mid-encode."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id, "req": req}
        try:
            view = res.view_name(view)
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            vmin = None if vmin in (None, "") else float(vmin)
            vmax = None if vmax in (None, "") else float(vmax)
            key = (run_id, view, cm, int(fps), vmin, vmax)
            hit = self.views.get(key)
            if hit is not None:
                return {"ok": True, "run_id": run_id, "req": req, "view": view, "cmap": cm,
                        "video": hit, "cached": True}
            if req is not None:                                      # tokens grow monotonically per client
                if req < self._latest.get(run_id, req):
                    return {"ok": False, "error": "superseded", "superseded": True, "run_id": run_id, "req": req}
                self._latest[run_id] = req
            with self._encode:
                if req is not None and self._latest.get(run_id) != req:
                    return {"ok": False, "error": "superseded", "superseded": True, "run_id": run_id, "req": req}
                vid = _b64_mp4(self._frames(res, view, cm, fps, run_id=run_id, req=req, vmin=vmin, vmax=vmax), fps)
            self.views.put(key, vid)
            return {"ok": True, "run_id": run_id, "req": req, "view": view, "cmap": cm, "video": vid, "cached": False}
        except _Superseded:
            return {"ok": False, "error": "superseded", "superseded": True, "run_id": run_id, "req": req}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id, "req": req}

    def preview_frame(self, run_id, view, cmap=None, frac=1.0, req=None, vmin=None, vmax=None):
        """One frame of a view as PNG — an instant preview for palette / limit changes.
        `frac` in [0, 1] picks the frame by position in the clip."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id, "req": req}
        try:
            view = res.view_name(view)
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            vmin = None if vmin in (None, "") else float(vmin)
            vmax = None if vmax in (None, "") else float(vmax)
            frac = float(frac); i = int(round(max(0.0, min(1.0, frac)) * (res.nframes - 1)))
            img = res.frame(i, view, cm, vmin, vmax)
            return {"ok": True, "run_id": run_id, "req": req, "view": view, "cmap": cm, "index": i,
                    "time": float(res.times[i]), "img": _b64_png(img)}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id, "req": req}

    def estimate(self, exhibit, params):
        """Rough resource estimate for a run before it starts (grid, frames, memory, time)."""
        try:
            return {"ok": True, **engine.estimate(exhibit, params or {})}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

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
            with self._encode:
                (render.save_gif if fmt == "gif" else render.save_mp4)(res.iter_frames(view, cm), path, fps=26)
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

    # ---------- experiments: projects, sweeps, comparison, probes ----------
    def project(self, scene, exhibit, params, view=None, cmap=None, advanced=False, run_id=None):
        """The complete resolved setup as a JSON-able project record."""
        val = schema.validate(exhibit, params or {}, allow_outside=True)
        rec = {"app": "Funoos", "version": APP_VERSION, "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "scene": scene, "exhibit": exhibit, "params": val.params, "advanced": bool(advanced),
               "derived": schema.derived(exhibit, val.params), "view": view, "cmap": cmap,
               "solver_versions": engine.solver_versions()}
        res = self.store.result(run_id) if run_id else None
        if res is not None:
            rec["result"] = res.meta()
            with self._lock:
                job = self._jobs.get(run_id)
            rec["status"] = job.state if job else "completed"
        return rec

    def save_project(self, scene, exhibit, params, view=None, cmap=None, advanced=False, run_id=None):
        """Write the resolved setup to a user-chosen .funoos.json file."""
        if not self._win:
            return {"ok": False, "error": "no window"}
        try:
            import webview
            rec = self.project(scene, exhibit, params, view, cmap, advanced, run_id)
            name = "".join(c if c.isalnum() else "_" for c in (scene or exhibit)).strip("_")[:40] or "experiment"
            sel = self._win.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{name}.funoos.json",
                                               file_types=("Funoos setup (*.json)", "All files (*.*)"))
            if not sel:
                return {"ok": True, "path": None}
            path = sel[0] if isinstance(sel, (list, tuple)) else sel
            if not path.lower().endswith(".json"):
                path += ".json"
            Path(path).write_text(json.dumps(rec, indent=2))
            return {"ok": True, "path": path}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    def load_project(self):
        """Open a saved setup; returns the record (validated against the current schema)."""
        if not self._win:
            return {"ok": False, "error": "no window"}
        try:
            import webview
            sel = self._win.create_file_dialog(webview.OPEN_DIALOG, allow_multiple=False,
                                               file_types=("Funoos setup (*.json)", "All files (*.*)"))
            if not sel:
                return {"ok": True, "config": None}
            path = sel[0] if isinstance(sel, (list, tuple)) else sel
            return self.load_project_file(path)
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    def load_project_file(self, path):
        try:
            rec = json.loads(Path(path).read_text())
            if not isinstance(rec, dict) or rec.get("app") != "Funoos" or "exhibit" not in rec:
                return {"ok": False, "error": "not a Funoos setup file"}
            if rec["exhibit"] not in engine.EXHIBITS:
                return {"ok": False, "error": f"unknown exhibit in file: {rec['exhibit']}"}
            val = schema.validate(rec["exhibit"], rec.get("params") or {}, allow_outside=True)
            rec["params"] = val.params
            rec["validation"] = val.as_dict()
            return {"ok": True, "config": rec, "path": str(path)}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    MAX_SWEEP = 8

    def sweep(self, exhibit, params, name, values, view=None, cmap=None, job_id=None, advanced=False):
        """Run the same setup for each value of one parameter (bounded queue, cancellable
        as one job). Each result is stored like a normal run; the reply carries the
        readouts and a thumbnail per value plus a readout-vs-value plot."""
        try:
            values = [float(v) for v in (values or [])][: self.MAX_SWEEP]
        except (TypeError, ValueError):
            return {"ok": False, "error": "sweep values must be numbers"}
        if not values or exhibit not in engine.EXHIBITS:
            return {"ok": False, "error": "nothing to sweep"}
        spec = {q["name"]: q for q in engine.EXHIBITS[exhibit]["params"]}
        if name not in spec or spec[name].get("type", "float") not in ("float", "int"):
            return {"ok": False, "error": f"{name} is not a numeric parameter"}
        job = self._new_job(exhibit, dict(params or {}, **{name: values[0]}), view, cmap, job_id)
        items = []; errors = []
        try:
            job.set_state("running")
            for k, val_ in enumerate(values):
                if job.cancel.is_set():
                    raise engine.Cancelled()
                p = dict(params or {}); p[name] = val_
                v = schema.validate(exhibit, p, allow_outside=bool(advanced))
                if not v.ok:
                    errors.append({"value": val_, "error": "; ".join(v.errors)}); continue
                self._emit_progress(job.id, f"sweep {k + 1}/{len(values)}: {name} = {val_:g}")
                res = engine.solve_exhibit(exhibit, v.params, progress=lambda m: self._emit_progress(job.id, f"[{k + 1}/{len(values)}] {m}"),
                                           cancel=job.cancel)
                rid = f"{job.id}-{k}"
                self.store.add(rid, res, res.info)
                vw = res.view_name(view); cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
                metrics = postproc.metrics(res) if hasattr(postproc, "metrics") else {}
                if not metrics:                                    # fall back to the numeric readouts
                    for st in _stats(res, exhibit):
                        try:
                            metrics[st["l"]] = float(st["v"])
                        except (TypeError, ValueError):
                            pass
                items.append({"value": val_, "run_id": rid, "info": res.info, "stats": _stats(res, exhibit),
                              "metrics": metrics, "frame": _b64_png(res.frame(-1, vw, cm))})
            job.set_state("completed"); job.run_id = items[-1]["run_id"] if items else None
            plot = None
            nums = [(it["value"], it["metrics"]) for it in items if it.get("metrics")]
            if nums:
                keys = [k for k in nums[0][1] if isinstance(nums[0][1][k], (int, float))]
                if keys:
                    key = keys[0]
                    xs = [x for x, m in nums if isinstance(m.get(key), (int, float))]
                    ys = [m[key] for x, m in nums if isinstance(m.get(key), (int, float))]
                    if len(xs) >= 2:
                        fig, ax, plt = postproc._new_ax(spec[name].get("label", name), key, f"{key} vs {spec[name].get('label', name)}")
                        ax.plot(xs, ys, "o-", color=postproc._CYAN, lw=2)
                        plot = _b64_png(postproc._rgb(fig, plt))
            return {"ok": True, "job_id": job.id, "state": "completed", "name": name, "items": items,
                    "errors": errors, "plot": plot, "views": list(engine.VIEWS.values())[0] if not items else None}
        except engine.Cancelled:
            job.set_state("cancelled")
            return {"ok": False, "job_id": job.id, "state": "cancelled", "error": "cancelled", "items": items}
        except Exception as e:                      # noqa: BLE001
            job.error = _errtext(e); job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error, "items": items}

    def compare(self, run_a, run_b, view, cmap=None, fps=26, req=None):
        """Side-by-side clip of two stored runs, synchronised by simulation time (or clip
        fraction when the time units differ), drawn with one shared colour scale."""
        a = self.store.result(run_a); b = self.store.result(run_b)
        if a is None or b is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[a.kind]
            frames = analysis.compare_frames(a, b, view, cm)
            times = []

            def gen():
                for fr, t in frames:
                    times.append(t); yield fr
            with self._encode:
                vid = _b64_mp4(gen(), fps)
            return {"ok": True, "req": req, "video": vid, "times": times, "run_a": run_a, "run_b": run_b,
                    "synchronised": a.hints.get("time_unit") == b.hints.get("time_unit"),
                    "info": f"{a.info}   |   {b.info}"}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def inspect(self, run_id, view, xfrac, yfrac, when=1.0, req=None):
        """Field value at a point of the rendered frame (fractions of the FRAME incl. the
        colourbar panel, +y up); returns None for solid/empty cells."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            pf = analysis.panel_fraction(res, view)
            xf = float(xfrac) / max(1e-9, 1.0 - pf)
            if xf > 1.0:
                return {"ok": True, "req": req, "outside": True}
            out = analysis.value_at(res, view, xf, float(yfrac), when)
            return {"ok": True, "req": req, "outside": False, **out}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def probe(self, run_id, view, xfrac, yfrac, req=None):
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            pf = analysis.panel_fraction(res, view)
            xf = min(1.0, float(xfrac) / max(1e-9, 1.0 - pf))
            ser = analysis.probe_series(res, view, xf, float(yfrac))
            fig, ax, plt = postproc._new_ax(f"time ({ser['time_unit']})", ser["label"], f"Probe at ({ser['ix']}, {ser['iy']})")
            ax.plot(ser["times"], [np.nan if v is None else v for v in ser["values"]], color=postproc._CYAN, lw=2)
            return {"ok": True, "req": req, **ser, "plot": _b64_png(postproc._rgb(fig, plt))}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def line_profile(self, run_id, view, axis="x", frac=0.5, when=1.0, req=None):
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            pr = analysis.line_profile(res, view, axis, float(frac), when)
            fig, ax, plt = postproc._new_ax("position (fraction)" if axis == "x" else pr["label"],
                                            pr["label"] if axis == "x" else "height (fraction)",
                                            f"Profile along {axis} at t = {pr['time']:g}")
            vals = [np.nan if v is None else v for v in pr["values"]]
            if axis == "x":
                ax.plot(pr["pos"], vals, color=postproc._AMBER, lw=2)
            else:
                ax.plot(vals, pr["pos"], color=postproc._AMBER, lw=2)
            return {"ok": True, "req": req, **pr, "plot": _b64_png(postproc._rgb(fig, plt))}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def export_csv(self, run_id, kind="probe", opts=None):
        """Save a probe series / line profile / diagnostic time series as CSV."""
        kw = dict(opts or {})
        if not self._win:
            return {"ok": False, "error": "no window"}
        try:
            import webview, csv
            res = self.store.result(run_id)
            if res is None:
                return {"ok": False, "error": "run expired"}
            if kind == "probe":
                d = analysis.probe_series(res, kw.get("view"), float(kw.get("xfrac", 0.5)), float(kw.get("yfrac", 0.5)))
                rows = [("time", d["label"])] + list(zip(d["times"], d["values"]))
            elif kind == "profile":
                d = analysis.line_profile(res, kw.get("view"), kw.get("axis", "x"), float(kw.get("frac", 0.5)))
                rows = [("position", d["label"])] + list(zip(d["pos"], d["values"]))
            else:
                series = postproc.series(res) if hasattr(postproc, "series") else {}
                if not series:
                    return {"ok": False, "error": "no time series for this run"}
                keys = list(series); n = len(series[keys[0]])
                rows = [tuple(keys)] + [tuple(series[k][i] for k in keys) for i in range(n)]
            sel = self._win.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"funoos_{kind}.csv",
                                               file_types=("CSV (*.csv)", "All files (*.*)"))
            if not sel:
                return {"ok": True, "path": None}
            path = sel[0] if isinstance(sel, (list, tuple)) else sel
            with open(path, "w", newline="") as f:
                csv.writer(f).writerows(rows)
            return {"ok": True, "path": path}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e)}

    # ---------- result store ----------
    def runs(self):
        return {"ok": True, "runs": self.store.summary(), "max_runs": self.store.max_runs,
                "max_bytes": self.store.max_bytes, "bytes": self.store.total_bytes(),
                "disk_bytes": self.store.disk_total(), "disk_max": self.store.disk_bytes}

    def pin_run(self, run_id, pinned=True):
        if not self.store.pin(run_id, pinned):
            return {"ok": False, "error": "run expired", "run_id": run_id}
        return {"ok": True, "run_id": run_id, "pinned": bool(pinned)}

    def set_budget(self, max_runs=None, memory_mb=None):
        evicted = self.store.set_limits(max_runs, None if memory_mb is None else float(memory_mb) * 2 ** 20)
        for rid in evicted:
            self.views.drop_run(rid)
        return {"ok": True, "evicted": evicted, **self.runs()}

    # ---------- lifecycle ----------
    def shutdown(self):
        """Stop every active job and kill live solver processes (window close / exit)."""
        self.cancel_all()
        killed = engine.kill_all_solvers()
        self.store.clear()
        return {"ok": True, "killed": killed}


def selftest():
    """Run a small representative pipeline with the bundled solvers, font and encoder
    (no window). Used by the build scripts and CI on the packaged app. Exit code 0 = ok."""
    import numpy as np
    t0 = time.time(); problems = []
    try:
        from flowzoo import geometry
        m = geometry.text(120, 40, "Fu", font_frac=0.5)
        assert m.sum() > 20, "text mask empty"
    except Exception as e:                      # noqa: BLE001
        problems.append(f"font/text geometry: {_errtext(e)}")
    for name, params in (("Turing Patterns", {"resolution": "Low (fast)", "duration": 0.05}),
                         ("Wind Tunnel", {"resolution": "Low (fast)", "duration": 0.05}),
                         ("The Big Splash", {"duration": 0.05, "particles": 600}),
                         ("Shock Tube", {"resolution": "Low (fast)", "duration": 0.2})):
        try:
            res = engine.solve_exhibit(name, params)
            frames = res.render(res.views[0])
            with tempfile.TemporaryDirectory(prefix=engine.TMP_PREFIX) as d:
                render.save_mp4(frames[:5], Path(d) / "t.mp4", fps=10)
                n, w, h, _ = render.video_info(Path(d) / "t.mp4")
                assert n == 5 and w > 0, "encoder round trip"
            postproc.metrics(res)
        except Exception as e:                  # noqa: BLE001
            problems.append(f"{name}: {_errtext(e)}")
    ok = not problems
    print(f"Funoos {APP_VERSION} self-test: {'OK' if ok else 'FAILED'} ({time.time() - t0:.1f}s)")
    for p in problems:
        print("  -", p)
    return 0 if ok else 1


def _platform_hint(err):
    if sys.platform.startswith("linux"):
        return ("pywebview needs a GUI backend on Linux: install either GTK (python3-gi, gir1.2-webkit2-4.1) "
                "or Qt (pip install pywebview[qt]). See https://pywebview.flowrl.com/guide/installation.html")
    if sys.platform.startswith("win"):
        return ("On Windows the WebView2 Evergreen runtime must be installed "
                "(https://developer.microsoft.com/microsoft-edge/webview2/); it is preinstalled on Windows 10/11.")
    return str(err)


def _webview2_present():
    """Windows only: is the WebView2 runtime registered? (None = not Windows / unknown)"""
    if not sys.platform.startswith("win"):
        return None
    try:
        import winreg
        for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                          (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")):
            try:
                with winreg.OpenKey(root, key):
                    return True
            except OSError:
                continue
        return False
    except Exception:                           # noqa: BLE001
        return None


def main():
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        import webview
    except Exception as e:                      # noqa: BLE001
        print("pywebview could not be imported.  pip install -r requirements.txt\n" + _platform_hint(e))
        return
    if _webview2_present() is False:
        print("WebView2 runtime not found: install the Evergreen runtime from Microsoft, then start Funoos again.")
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
