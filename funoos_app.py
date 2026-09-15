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
import math
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

import numpy as np

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

    def refresh(self, run_id):
        """Re-count a run's bytes after its derived caches grew; evict if the budget is exceeded
        (the run itself is kept)."""
        with self._lock:
            r = self._runs.get(run_id)
            if not r:
                return []
            res = r["result"]
            r["bytes"] = max(0, result_bytes(res) - r.get("disk", 0)) + (res.cache_bytes() if hasattr(res, "cache_bytes") else 0)
            return self._evict(keep=run_id)

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
        self.provenance = {"app_version": APP_VERSION, "solver_versions": engine.solver_versions(),
                           "started": time.strftime("%Y-%m-%dT%H:%M:%S")}       # frozen when the job is created

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
                "provenance": self.provenance, "parent": getattr(self, "parent", None),
                "history": [{"state": s, "t": t} for s, t in self.history]}


def _frame_sel(res, when):
    """Frame index from a clip fraction, an explicit {'index': i} / {'time': t} dict, or None (last)."""
    if isinstance(when, dict):
        if when.get("index") is not None:
            return int(when["index"]) % res.nframes
        if when.get("time") is not None:
            return analysis.frame_index(res, {"time": float(when["time"])})
        when = when.get("frac", 1.0)
    if when is None:
        return res.nframes - 1
    return analysis.frame_index(res, float(when))


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
MAX_VIEW_CACHE_MB = float(os.environ.get("FUNOOS_VIEW_CACHE_MB", "96"))   # and at most this many MB of encoded clips


class ViewCache:
    """LRU cache of encoded clips keyed by (run_id, view, cmap, fps, vmin, vmax), bounded by
    count AND total bytes."""

    def __init__(self, max_items=MAX_VIEW_CACHE, max_bytes=int(MAX_VIEW_CACHE_MB * 2 ** 20)):
        self.max_items = max(1, int(max_items)); self.max_bytes = int(max_bytes); self._d = {}; self._lock = threading.Lock()

    def total_bytes(self):
        return sum(len(v) for v in self._d.values())

    def get(self, key):
        with self._lock:
            v = self._d.pop(key, None)
            if v is not None:
                self._d[key] = v                 # most recently used
            return v

    def put(self, key, value):
        with self._lock:
            self._d[key] = value
            while len(self._d) > 1 and (len(self._d) > self.max_items or self.total_bytes() > self.max_bytes):
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


# Readouts shown under the stage: measurement key, label, unit, scale (first four available are shown).
_READOUTS = [
    ("cl_circulation", "Lift C_l", "", 1.0), ("cd_wake_approx", "Drag C_d (wake estimate)", "", 1.0), ("strouhal", "Strouhal St", "", 1.0),
    ("permeability_cells2", "Permeability k", "cells²", 1.0), ("porosity", "Porosity φ", "", 1.0),
    ("nusselt", "Nusselt Nu", "", 1.0), ("mixing_width_final_frac", "Mixing width (end)", "of height", 1.0),
    ("shock_radius_final_cells", "Shock radius (end)", "cells", 1.0),
    ("sod_err_rho", "Density error vs exact", "", 1.0), ("sod_err_u", "Velocity error vs exact", "", 1.0),
    ("ke_peak", "Peak kinetic energy", "", 1.0), ("ke_final", "Kinetic energy (end)", "", 1.0), ("ke_drift_rel", "Energy change", "%", 100.0),
    ("enstrophy_final", "Enstrophy (end)", "", 1.0), ("pattern_coverage_pct", "Pattern coverage", "%", 1.0),
    ("dye_variance_final", "Dye variance (end)", "", 1.0), ("particles_final", "Particles", "", 1.0), ("norm_drift", "Norm drift", "", 1.0),
]


def _stats(res, exhibit):
    """Readouts for the strip under the stage: the run's measurements (postproc.metrics, the same
    numbers the diagnostics explain), then the simulated time and the number of frames. Missing or
    non-finite measurements are left out rather than shown as zero."""
    out = []
    try:
        m = postproc.metrics(res)
    except Exception:                                   # noqa: BLE001 - readouts are advisory
        m = {}
    for key, label, unit, scale in _READOUTS:
        v = m.get(key)
        if v is None or not np.isfinite(v):
            continue
        val = float(v) * scale
        txt = str(int(round(val))) if key == "particles_final" else f"{val:.3g}"
        out.append({"l": label, "v": txt, "u": unit, "accent": not out})
        if len(out) >= 4:
            break
    try:
        times = [float(t) for t in (getattr(res, "times", None) or [])]
        if times:
            out.append({"l": "simulated time", "v": f"{times[-1]:.4g}", "u": (res.hints or {}).get("time_unit", "")})
    except Exception:                                   # noqa: BLE001
        pass
    out.append({"l": "frames", "v": str(len(res.raw))})
    return out


def _js(s):
    return json.dumps(s)


def _json_safe(obj):
    """Make a response strictly JSON-serialisable: NaN/±inf → None, numpy scalars/arrays → Python."""
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return _json_safe(obj.tolist())
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (float, np.floating)):
        f = float(obj)
        return f if math.isfinite(f) else None
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (str, int, bool)) or obj is None:
        return obj
    return str(obj)


def _api_method(fn):
    """Every public Api method returns a strictly JSON-safe envelope."""
    import functools

    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        out = fn(self, *args, **kwargs)
        return _json_safe(out)
    wrapper._api = True
    return wrapper



def _initial_window_size(pref=(1440, 900)):
    """A window that fits the screen it opens on: at most 1440x900 and at most 92 % x 86 % of the
    screen (room for the taskbar or menu bar and the title bar); 1440x900 when the screen size is
    unknown. pywebview sizes are logical pixels, so display scaling (125 %, 150 %) is respected."""
    try:
        import webview
        screens = webview.screens() if callable(webview.screens) else webview.screens
        scr = screens[0]
        sw, sh = int(scr.width), int(scr.height)
        if sw < 640 or sh < 480:
            return pref
        return int(min(pref[0], sw * 0.92)), int(min(pref[1], sh * 0.86))
    except Exception:                                   # noqa: BLE001 - no display information yet
        return pref


def scene_for_run(exhibit, params):
    """The catalogue scene a run belongs to: the most specific preset of its exhibit whose values
    are all contained in the run's parameters (None when no preset of that exhibit matches)."""
    scene, best = None, -1
    for sc in catalog.SCENES:
        pre = sc["preset"]
        if sc["exhibit"] == exhibit and len(pre) > best and all(params.get(k) == v for k, v in pre.items()):
            scene, best = sc["key"], len(pre)
    return scene

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
        """Experiments (gallery cards) grouped by phenomenon, each with its named presets."""
        exps = catalog.experiments()
        by_phen = {}
        for e in exps:
            for pz in e["presets"]:
                sc = catalog.scene(pz["key"]); mp4 = ROOT / "results" / "gallery" / (pz["key"] + ".mp4")
                pz["clip"] = ("results/gallery/" + pz["key"] + ".mp4") if mp4.exists() else None
                pz["poster"] = ("results/gallery/" + pz["key"] + ".jpg") if (ROOT / "results" / "gallery" / (pz["key"] + ".jpg")).exists() else None
                th = ROOT / "results" / "gallery" / "thumbs"      # card thumbnails (tools/make_thumbs.py)
                pz["thumb"] = ("results/gallery/thumbs/" + pz["key"] + ".mp4") if (th / (pz["key"] + ".mp4")).exists() else None
                pz["thumb_poster"] = ("results/gallery/thumbs/" + pz["key"] + ".jpg") if (th / (pz["key"] + ".jpg")).exists() else None
                pz["question"] = sc["question"]; pz["blurb"] = sc["blurb"]
                pz["estimate_s"] = engine.estimate(sc["exhibit"], sc["preset"]).get("seconds")
            rep = next((pz for pz in e["presets"] if pz["key"] == e["representative"]), e["presets"][0])
            e["clip"] = rep["clip"]; e["poster"] = rep["poster"]; e["status"] = rep["status"]; e["status_label"] = rep["status_label"]
            e["thumb"] = rep["thumb"] or rep["clip"]; e["thumb_poster"] = rep["thumb_poster"] or rep["poster"]
            e["estimate_s"] = min([pz["estimate_s"] for pz in e["presets"] if pz["estimate_s"] is not None] or [None])
            by_phen.setdefault(e["phenomenon"], []).append(e)
        groups = [{"phenomenon": p, "experiments": by_phen[p]} for p in catalog.PHENOMENA if p in by_phen]
        return {"ok": True, "groups": groups, "methods": sorted({s["method"] for s in catalog.SCENES}),
                "counts": catalog.counts(), "scene_to_experiment": {s["key"]: catalog.experiment_of(s["key"])["id"] for s in catalog.SCENES}}

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
                "poster": ("results/gallery/" + key + ".jpg") if (ROOT / "results" / "gallery" / (key + ".jpg")).exists() else None,
                "preset": s["preset"], "layers": catalog.scene_layers(key)["layers"],
                "experiment": self._experiment_ctx(key),
                "cmap": s.get("cmap"), "params": _param_spec(ex), "method_label": m.get("method", "")}

    @staticmethod
    def _experiment_ctx(key):
        e = catalog.experiment_of(key)
        if not e:
            return None
        return {"id": e["id"], "name": e["name"], "question": e["question"], "preset_label": catalog.preset_label(key),
                "presets": [{"key": k, "label": lab, "exhibit": catalog.scene(k)["exhibit"]} for k, lab in e["presets"]],
                "compare": [{"a": x, "b": y, "text": t} for x, y, t in e.get("compare", [])]}

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
            job.set_state("completed")                    # terminal state first; readouts below are advisory

            def advisory(fn, default):
                try:
                    return fn(), None
                except Exception as e:              # noqa: BLE001 — a readout problem never fails a completed run
                    return default, _errtext(e)
            stats, stats_note = advisory(lambda: _stats(res, exhibit), [])
            derived_items, derived_note = advisory(lambda: schema.derived(exhibit, dict(job.params)), [])
            meta, _ = advisory(res.meta, {"kind": res.kind, "frames": res.nframes})
            return {"ok": True, "job_id": job.id, "run_id": job.id, "state": "completed",
                    "video": vid, "views": list(res.views), "view": view, "info": res.info,
                    "cmaps": list(render.COLORMAPS), "defcmap": cm, "stats": stats,
                    "params": dict(job.params), "evicted": evicted, "meta": meta,
                    "validation": val.as_dict(), "derived": derived_items,
                    "stats_note": stats_note or derived_note,
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
            for rid in self.store.refresh(run_id):
                self.views.drop_run(rid)
            return {"ok": True, "run_id": run_id, "req": req, "view": view, "cmap": cm, "video": vid, "cached": False,
                    "field_rect": analysis.field_rect(res, view)}
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
            i = _frame_sel(res, frac)
            img = res.frame(i, view, cm, vmin, vmax)
            self.store.refresh(run_id)
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

    def _ask_save(self, default_name, fmt, label):
        import webview
        sel = self._win.create_file_dialog(webview.SAVE_DIALOG, save_filename=f"{default_name}.{fmt}",
                                           file_types=(f"{label} (*.{fmt})", "All files (*.*)"))
        if not sel:
            return None
        path = sel[0] if isinstance(sel, (list, tuple)) else sel
        return path if path.lower().endswith("." + fmt) else path + "." + fmt

    @staticmethod
    def _slug(res):
        return "".join(c if c.isalnum() else "_" for c in res.info.split("·")[0]).strip("_")[:40] or "funoos"

    def save_clip(self, run_id, view, cmap=None, fmt="mp4", opts=None):
        """Render a view and save it as MP4 or GIF. `opts`: fps (default 26), scale (output size
        multiplier, e.g. 0.5 or 2), t0/t1 (clip fraction window, 0..1), vmin/vmax (colour limits).
        `path` is None when the user dismissed the dialog."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id}
        if not self._win:
            return {"ok": False, "error": "no window", "run_id": run_id}
        try:
            o = dict(opts or {})
            view = res.view_name(view)
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            fmt = "gif" if str(fmt).lower() == "gif" else "mp4"
            fps = int(o.get("fps") or 26); scale = float(o.get("scale") or 1.0)
            t0 = float(o.get("t0") or 0.0); t1 = float(o.get("t1") if o.get("t1") not in (None, "") else 1.0)
            vmin = None if o.get("vmin") in (None, "") else float(o["vmin"]); vmax = None if o.get("vmax") in (None, "") else float(o["vmax"])
            path = self._ask_save(self._slug(res), fmt, fmt.upper())
            if not path:
                return {"ok": True, "path": None, "run_id": run_id}
            n = res.nframes; i0 = int(round(max(0.0, min(1.0, t0)) * (n - 1))); i1 = int(round(max(0.0, min(1.0, t1)) * (n - 1)))
            i0, i1 = min(i0, i1), max(i0, i1)

            def gen():
                from PIL import Image
                for i, fr in enumerate(res.iter_frames(view, cm, vmin, vmax)):
                    if i < i0 or i > i1:
                        continue
                    if scale != 1.0:
                        im = Image.fromarray(fr); fr = np.asarray(im.resize((max(2, int(im.width * scale)), max(2, int(im.height * scale))), Image.LANCZOS))
                    yield fr
            with self._encode:
                (render.save_gif if fmt == "gif" else render.save_mp4)(gen(), path, fps=fps)
            return {"ok": True, "path": path, "run_id": run_id, "frames": i1 - i0 + 1, "fps": fps}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id}

    def save_png(self, run_id, view, cmap=None, frac=1.0, vmin=None, vmax=None):
        """Save the frame on screen (clip fraction `frac`) as a PNG."""
        res = self.store.result(run_id)
        if res is None or not self._win:
            return {"ok": False, "error": "run expired" if res is None else "no window", "run_id": run_id}
        try:
            view = res.view_name(view); cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            vmin = None if vmin in (None, "") else float(vmin); vmax = None if vmax in (None, "") else float(vmax)
            i = _frame_sel(res, frac)
            path = self._ask_save(f"{self._slug(res)}_{view.replace(' ', '_')}_f{i:03d}", "png", "PNG image")
            if not path:
                return {"ok": True, "path": None}
            render.save_png(res.frame(i, view, cm, vmin, vmax), path)
            return {"ok": True, "path": path, "index": i, "time": float(res.times[i])}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id}

    def save_plots_svg(self, run_id):
        """Save every diagnostic plot of a run as SVG files (one per plot) next to a chosen name."""
        res = self.store.result(run_id)
        if res is None or not self._win:
            return {"ok": False, "error": "run expired" if res is None else "no window", "run_id": run_id}
        try:
            path = self._ask_save(f"{self._slug(res)}_plots", "svg", "SVG plots")
            if not path:
                return {"ok": True, "paths": []}
            base = Path(path).with_suffix(""); paths = []
            for k, (title, svg, _ex) in enumerate(postproc.plots_svg(res)):
                pth = Path(f"{base}_{k + 1}_{''.join(c if c.isalnum() else '_' for c in title)[:30]}.svg")
                pth.write_text(svg); paths.append(str(pth))
            return {"ok": True, "paths": paths}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id}

    def save_arrays(self, run_id):
        """Save the raw fields with coordinates, timestamps, names and units as a .npz file."""
        res = self.store.result(run_id)
        if res is None or not self._win:
            return {"ok": False, "error": "run expired" if res is None else "no window", "run_id": run_id}
        try:
            path = self._ask_save(f"{self._slug(res)}_fields", "npz", "NumPy arrays")
            if not path:
                return {"ok": True, "path": None}
            arrays = {"times": np.asarray(res.times, float)}
            h = res.hints; meta = {"kind": res.kind, "info": res.info, "time_unit": h.get("time_unit", "frame"),
                                   "length_unit": "lattice cells" if res.kind in ("lbm", "porous") else ("m" if res.kind == "particles" else "grid units"),
                                   "convention": "arrays are [frame, y, x] with y increasing upward; particles are [frame][particle, (x, y, speed)]"}
            f0 = res.raw[0]
            if isinstance(f0, tuple):
                arrays["ux"] = np.stack([f[0] for f in res.raw]); arrays["uy"] = np.stack([f[1] for f in res.raw])
                ny, nx = f0[0].shape; meta["fields"] = "ux, uy (velocity components)"
            elif getattr(f0, "ndim", 0) == 2 and f0.shape[1] == 3 and res.kind == "particles":
                for i, f in enumerate(res.raw):
                    arrays[f"particles_{i:04d}"] = np.asarray(f)
                nx = ny = None; meta["fields"] = "particles_NNNN: x, y, speed per particle"
            else:
                arrays[h.get("label", "scalar").replace(" ", "_")] = np.stack(res.raw); ny, nx = f0.shape
                meta["fields"] = h.get("label", "scalar")
                if isinstance(h.get("vel"), list):
                    arrays["ux"] = np.stack([f[0] for f in h["vel"]]); arrays["uy"] = np.stack([f[1] for f in h["vel"]])
            if nx:
                dx = float(h.get("dx", 1.0)); arrays["x"] = np.arange(nx) * dx; arrays["y"] = np.arange(ny) * dx
            if res.mask is not None:
                arrays["solid_mask"] = np.asarray(res.mask, np.uint8)
            arrays["meta_json"] = np.array(json.dumps({**meta, "hints": res.meta()["hints"]}))
            np.savez_compressed(path, **arrays)
            return {"ok": True, "path": path, "arrays": sorted(arrays)}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "run_id": run_id}

    def save_report(self, run_id, scene=None, view=None, cmap=None):
        """A compact self-contained HTML report: settings, derived quantities, selected
        figures, measurements and model notes, traceable to the run."""
        res = self.store.result(run_id)
        if res is None or not self._win:
            return {"ok": False, "error": "run expired" if res is None else "no window", "run_id": run_id}
        try:
            path = self._ask_save(f"{self._slug(res)}_report", "html", "HTML report")
            if not path:
                return {"ok": True, "path": None}
            with self._lock:
                job = self._jobs.get(run_id)
            exhibit = job.exhibit if job else None
            params = dict(job.params) if job else {}
            rec = self.project(scene, exhibit, params, view, cmap, False, run_id) if exhibit else {"result": res.meta()}
            if rec.get("run"):
                rec["solver_versions"] = rec["run"]["provenance"].get("solver_versions"); rec["derived"] = schema.derived(exhibit, rec["run"]["params"])
            view = res.view_name(view); cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
            still = _b64_png(res.frame(-1, view, cm))
            plots = [(t, _b64_png(img), ex) for t, img, ex in postproc.plots(res)]
            mets = postproc.metrics(res)
            sc = catalog.scene(scene) if scene else None
            lay = catalog.scene_layers(scene) if sc else None
            esc = lambda x: str(x).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")   # noqa: E731
            h = [f"<!doctype html><html><head><meta charset='utf-8'><title>Funoos report — {esc(res.info)}</title>",
                 "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:30px auto;padding:0 16px;color:#222}"
                 "table{border-collapse:collapse}td,th{border:1px solid #ccc;padding:4px 8px;font-size:13px}img{max-width:100%}"
                 "h2{margin-top:28px}.small{color:#666;font-size:12px}</style></head><body>",
                 f"<h1>{esc(sc['name'] if sc else res.info)}</h1>",
                 f"<p class='small'>Funoos {APP_VERSION} · run {esc(run_id)} · {esc(rec.get('saved', ''))} · status {esc(rec.get('status', 'completed'))}</p>"]
            if sc:
                h.append(f"<p><b>Question:</b> {esc(sc['question'])}<br><b>Status:</b> {esc(catalog.STATUS_LABEL[sc['status']])}</p>")
            h.append(f"<h2>Setup</h2><table><tr><th>parameter</th><th>value</th></tr>" +
                     "".join(f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in params.items()) + "</table>")
            if rec.get("derived"):
                h.append("<h2>Derived quantities</h2><table>" + "".join(
                    f"<tr><td>{esc(d['label'])}</td><td>{esc(d['value'])} {esc(d.get('units', ''))}</td><td class='small'>{esc(d.get('note', ''))}</td></tr>"
                    for d in rec["derived"]) + "</table>")
            m = res.meta()
            h.append(f"<h2>Result</h2><p>{esc(res.info)} · {m['frames']} frames · grid {esc(m['shape'])} · times {m['times'][0]:g} … {m['times'][-1]:g} {esc(m['time_unit'])}</p>")
            h.append(f"<p><img src='{still}' alt='final frame, {esc(view)}'><br><span class='small'>{esc(view)} view, final frame, palette {esc(cm)}</span></p>")
            if mets:
                h.append("<h2>Measurements</h2><table><tr><th>metric</th><th>value</th></tr>" +
                         "".join(f"<tr><td>{esc(k)}</td><td>{v:.6g}</td></tr>" for k, v in mets.items() if isinstance(v, (int, float))) + "</table>")
            for t, img, ex in plots:
                h.append(f"<h3>{esc(t)}</h3><img src='{img}' alt='{esc(t)}'><p class='small'>{esc(ex)}</p>")
            if lay:
                for L in lay["layers"]:
                    if L["id"] == "setup":
                        h.append(f"<h2>{esc(L['title'])}</h2><p>Initial: {esc(L.get('ic', ''))}<br>Boundary: {esc(L.get('bc', ''))}</p>")
                    elif L["id"] == "numerics":
                        h.append(f"<h2>Numerical method</h2><p>{esc(L.get('text') or '')}</p>")
                        h.append(f"<h2>Checks and limitations</h2><p><b>{esc(L.get('status', ''))}.</b> {esc(L.get('checks') or '')}</p>")
            if rec.get("solver_versions"):
                h.append("<h2>Provenance</h2><p class='small'>" + esc(json.dumps(rec["solver_versions"])) + "</p>")
            h.append(f"<hr><p class='small'>Generated with Funoos {esc(APP_VERSION)} (https://github.com/SalehMohammadrezaei/Funoos), "
                     "created by Saleh Mohammadrezaei, MIT licence. The results in this report belong to the user who produced them.</p>")
            h.append("</body></html>")
            Path(path).write_text("\n".join(h), encoding="utf-8")
            return {"ok": True, "path": path}
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
    def project(self, scene, exhibit, params, view=None, cmap=None, advanced=False, run_id=None, presentation=None):
        """The complete setup as a JSON-able record (schema_version 2).

        `draft` is the editable control state at save time; `run` (when a run is referenced)
        is that run's FROZEN configuration, metadata and provenance recorded when it started.
        The two are stored separately and `draft_matches_run` says whether they agree."""
        val = schema.validate(exhibit, params or {}, allow_outside=True)
        rec = {"app": "Funoos", "version": APP_VERSION, "schema_version": 2, "saved": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "scene": scene, "exhibit": exhibit, "params": val.params, "advanced": bool(advanced),
               "derived": schema.derived(exhibit, val.params), "effective": engine.effective(exhibit, val.params),
               "solver_versions": engine.solver_versions(),           # of the code at save time (the run's own are under run.provenance)
               "presentation": {"view": view, "cmap": cmap, **(presentation or {})}}
        res = self.store.result(run_id) if run_id else None
        with self._lock:
            job = self._jobs.get(run_id) if run_id else None
        if job is not None:
            rec["run"] = {"run_id": run_id, "exhibit": job.exhibit, "params": dict(job.params), "status": job.state,
                          "provenance": job.provenance, "parent": getattr(job, "parent", None),
                          "effective": engine.effective(job.exhibit, dict(job.params)) if job.exhibit in engine.EXHIBITS else {},
                          "result": res.meta() if res is not None else None}
            rec["draft_matches_run"] = (job.exhibit == exhibit and dict(job.params) == val.params)
        return rec

    def save_project(self, scene, exhibit, params, view=None, cmap=None, advanced=False, run_id=None, presentation=None):
        """Write the resolved setup to a user-chosen .funoos.json file."""
        if not self._win:
            return {"ok": False, "error": "no window"}
        try:
            import webview
            rec = self.project(scene, exhibit, params, view, cmap, advanced, run_id, presentation)
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
            if "presentation" not in rec:                     # schema_version 1 files
                rec["presentation"] = {"view": rec.get("view"), "cmap": rec.get("cmap")}
            rec.setdefault("schema_version", 1)
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
        # retention: a sweep must not evict its own children before it finishes; the count limit is
        # raised to hold them (the memory/disk budgets still apply, large results spill to disk)
        need = len(values) + 1
        if self.store.max_runs < need:
            self.store.max_runs = need
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
                rid = f"{job.id}-{k}"
                with self._lock:                                        # each child is a job of its own
                    child = Job(rid, exhibit, v.params, view, cmap); child.parent = job.id; child.set_state("running")
                    self._jobs[rid] = child
                try:
                    res = engine.solve_exhibit(exhibit, v.params, progress=lambda m: self._emit_progress(job.id, f"[{k + 1}/{len(values)}] {m}"),
                                               cancel=job.cancel)
                except Exception as e:                                  # noqa: BLE001
                    child.error = _errtext(e); child.set_state("cancelled" if isinstance(e, engine.Cancelled) else "failed")
                    raise
                child.run_id = rid; child.set_state("completed")
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
                    "errors": errors, "plot": plot, "retained": [it["run_id"] in self.store for it in items],
                    "store": {"runs": len(self.store), "max_runs": self.store.max_runs, "bytes": self.store.total_bytes(),
                              "disk_bytes": self.store.disk_total()}}
        except engine.Cancelled:
            job.set_state("cancelled")
            return {"ok": False, "job_id": job.id, "state": "cancelled", "error": "cancelled", "items": items}
        except Exception as e:                      # noqa: BLE001
            job.error = _errtext(e); job.set_state("failed")
            return {"ok": False, "job_id": job.id, "state": "failed", "error": job.error, "items": items}

    def compare(self, run_a, run_b, view, cmap=None, fps=26, req=None):
        """Side-by-side clip of two stored runs over their SHARED time interval, drawn with one
        colour scale. Requires the same solver family, view and time unit; the reply states the
        alignment so nothing is silently resampled or repeated."""
        a = self.store.result(run_a); b = self.store.result(run_b)
        if a is None or b is None:
            return {"ok": False, "error": "run expired", "req": req}
        ok, why = analysis.compare_check(a, b, view)
        if not ok:
            return {"ok": False, "error": "cannot compare: " + why, "req": req, "incompatible": True}
        try:
            cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[a.kind]
            grid, ia, ib, note = analysis.compare_plan(a, b)
            if not grid:
                return {"ok": False, "error": "cannot compare: " + note, "req": req, "incompatible": True}
            times = []; scale = {}

            def gen():
                for fr, t, (vmin, vmax) in analysis.compare_frames(a, b, view, cm):
                    times.append(t); scale["vmin"], scale["vmax"] = vmin, vmax; yield fr
            with self._encode:
                vid = _b64_mp4(gen(), fps)
            return {"ok": True, "req": req, "video": vid, "times": times, "run_a": run_a, "run_b": run_b, "view": a.view_name(view),
                    "cmap": cm, "vmin": scale.get("vmin"), "vmax": scale.get("vmax"), "time_unit": a.hints.get("time_unit", "frame"),
                    "note": note, "label_a": a.info, "label_b": b.info, "info": f"{a.info}   |   {b.info}", "frames": len(times)}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def inspect(self, run_id, view, xfrac, yfrac, when=1.0, req=None):
        """Field value at a point of the rendered frame (fractions of the FRAME incl. the
        colourbar panel, +y up); returns None for solid/empty cells."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            rc = analysis.field_rect(res, view)
            xf = (float(xfrac) - rc["x0"]) / max(1e-9, rc["w"]); yf = (float(yfrac) - rc["y0"]) / max(1e-9, rc["h"])
            if not (0.0 <= xf <= 1.0 and 0.0 <= yf <= 1.0):
                return {"ok": True, "req": req, "outside": True}
            out = analysis.value_at(res, view, xf, yf, {"index": _frame_sel(res, when)})
            return {"ok": True, "req": req, "outside": False, **out}
        except Exception as e:                      # noqa: BLE001
            return {"ok": False, "error": _errtext(e), "req": req}

    def probe(self, run_id, view, xfrac, yfrac, req=None):
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "req": req}
        try:
            rc = analysis.field_rect(res, view)
            xf = min(1.0, max(0.0, (float(xfrac) - rc["x0"]) / max(1e-9, rc["w"]))); yf = min(1.0, max(0.0, (float(yfrac) - rc["y0"]) / max(1e-9, rc["h"])))
            ser = analysis.probe_series(res, view, xf, yf)
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
            pr = analysis.line_profile(res, view, axis, float(frac), index=_frame_sel(res, when))
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
                # the SAME cell the plot used: resolved cell indices, not re-derived fractions
                d = analysis.probe_series(res, kw.get("view"), ix=int(kw["ix"]), iy=int(kw["iy"]))
                rows = [("# " + f"run {run_id}, view {kw.get('view')}, cell ({d['ix']}, {d['iy']}), time unit {d['time_unit']}", ""),
                        ("time", d["label"])] + list(zip(d["times"], d["values"]))
            elif kind == "profile":
                d = analysis.line_profile(res, kw.get("view"), kw.get("axis", "x"), index=int(kw["index"]),
                                          ix=kw.get("ix"), iy=kw.get("iy"))
                rows = [("# " + f"run {run_id}, view {kw.get('view')}, axis {d['axis']}, frame {d['index']}, time {d['time']}", ""),
                        ("position", d["label"])] + list(zip(d["pos"], d["values"]))
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

    def run_info(self, run_id):
        """Complete descriptor of a stored run: views, palettes, readouts, metadata, parameters,
        provenance, scene — everything the UI needs to display it as the current result."""
        res = self.store.result(run_id)
        if res is None:
            return {"ok": False, "error": "run expired", "run_id": run_id}
        with self._lock:
            job = self._jobs.get(run_id)
        exhibit = job.exhibit if job else None
        scene = scene_for_run(exhibit, dict(job.params)) if exhibit else None
        return {"ok": True, "run_id": run_id, "info": res.info, "views": list(res.views), "view": res.views[0],
                "cmaps": list(render.COLORMAPS), "defcmap": engine.DEFCMAP[res.kind], "stats": _stats(res, exhibit) if exhibit else [],
                "meta": res.meta(), "params": dict(job.params) if job else {}, "exhibit": exhibit, "scene": scene,
                "state": job.state if job else "completed", "provenance": job.provenance if job else None,
                "parent": getattr(job, "parent", None) if job else None,
                "derived": schema.derived(exhibit, dict(job.params)) if exhibit in engine.EXHIBITS else []}

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

    def about(self):
        import platform
        build = None
        try:
            from flowzoo import _build
            build = getattr(_build, "REVISION", None)
        except Exception:                           # noqa: BLE001
            try:
                import subprocess
                build = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=str(ROOT), capture_output=True, text=True, timeout=3).stdout.strip() or None
            except Exception:                       # noqa: BLE001
                build = None
        cit = (f"Mohammadrezaei, S. ({time.strftime('%Y')}). Funoos — fluid simulation laboratory (version {APP_VERSION}) [Computer software]. "
               "https://github.com/SalehMohammadrezaei/Funoos")
        return {"ok": True, "author": "Saleh Mohammadrezaei", "email": "salehmrezaee@gmail.com", "version": APP_VERSION, "build": build,
                "license": "MIT (see LICENSE and THIRD_PARTY_NOTICES.md)", "python": platform.python_version(),
                "links": [["GitHub repository", "https://github.com/SalehMohammadrezaei/Funoos"],
                          ["Releases", "https://github.com/SalehMohammadrezaei/Funoos/releases"]],
                "citation": cit,
                "acknowledgements": "Built with NumPy, SciPy, Matplotlib, Pillow, pywebview and ffmpeg (via imageio-ffmpeg); "
                                    "DejaVu fonts. Solver families follow published methods cited on each scene page."}

    def open_url(self, url):
        """Open an external link in the system browser (never inside the app window)."""
        import webbrowser
        if not isinstance(url, str) or not url.startswith(("https://", "http://")):
            return {"ok": False, "error": "only http(s) links can be opened"}
        webbrowser.open(url)
        return {"ok": True}

    def settings(self):
        return {"ok": True, "threads": int(engine._ENV.get("OMP_NUM_THREADS", "1")), "cpus": os.cpu_count() or 1,
                "max_runs": self.store.max_runs, "memory_mb": self.store.max_bytes / 2 ** 20, "disk_mb": self.store.disk_bytes / 2 ** 20,
                "view_cache_mb": self.views.max_bytes / 2 ** 20}

    def set_threads(self, n):
        """OpenMP threads for the next solver runs (0 = automatic default)."""
        n = int(n or 0); cpus = os.cpu_count() or 1
        engine._ENV["OMP_NUM_THREADS"] = str(min(cpus, n) if n > 0 else engine._default_threads())
        return {"ok": True, "threads": int(engine._ENV["OMP_NUM_THREADS"])}

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


for _name, _fn in list(vars(Api).items()):
    if callable(_fn) and not _name.startswith("_") and not getattr(_fn, "_api", False):
        setattr(Api, _name, _api_method(_fn))


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
    width, height = _initial_window_size()
    win = webview.create_window("Funoos — fluid simulation laboratory",
                                str(ROOT / "index.html"), js_api=api,
                                width=width, height=height, min_size=(min(1024, width), min(640, height)),
                                background_color="#0A1322")
    api._win = win
    def on_close():                                              # stop solvers when the window closes
        api.shutdown()
    win.events.closing += on_close
    atexit.register(api.shutdown)
    webview.start(http_server=True)


if __name__ == "__main__":
    main()
