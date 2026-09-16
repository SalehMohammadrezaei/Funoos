"""Funoos engine: solve an exhibit, then render any visualization on demand.

`solve_exhibit(name, params)` runs the solver once and returns a Result holding
the raw fields. `Result.render(view, colormap)` turns those into RGB frames —
so a GUI can switch Vorticity / Velocity / Streamlines / Density … instantly
without re-running. `run_exhibit(...)` is a convenience that solves and renders
the default view (used by the command-line demos).

Each exhibit exposes a parameter spec (geometry + physics + render, with help
text and ranges); `view` and `colormap` are chosen *after* the run.
"""
from __future__ import annotations

import os
import queue
import re
import collections
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

import numpy as np

from . import render, geometry

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
SOLVERS = _BASE / "solvers"
EXE = ".exe" if sys.platform.startswith("win") else ""
def _default_threads():
    """OpenMP threads for the C++ solvers. A user-set OMP_NUM_THREADS is respected;
    otherwise use up to 8 (measured on the wind tunnel: 1→22 s, 4→6 s, 8→4 s, 16→3 s —
    beyond 8 the 2-D grids gain little and would oversubscribe shared machines)."""
    env = os.environ.get("OMP_NUM_THREADS")
    if env and env.strip().isdigit() and int(env) > 0:
        return int(env)
    return min(8, os.cpu_count() or 4)


_ENV = {**os.environ, "OMP_NUM_THREADS": str(_default_threads())}

_STEP_RE = re.compile(r"step\s+(\d+)\s*/\s*(\d+)")
_T_RE = re.compile(r"\bt=([\d.]+)")


class Cancelled(Exception):
    """Raised inside a solve when its job was cancelled (see `solve_exhibit(cancel=...)`)."""


# Solver subprocesses that are currently alive, so the app can kill them on exit.
_LIVE_PROCS = set()
_LIVE_LOCK = threading.Lock()


def _kill(proc):
    if proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass


def kill_all_solvers():
    """Kill every running solver subprocess (app shutdown / crash cleanup)."""
    with _LIVE_LOCK:
        procs = list(_LIVE_PROCS); _LIVE_PROCS.clear()
    for proc in procs:
        _kill(proc)
    return len(procs)


def _run_solver(args, pr=None, tend=None, cancel=None):
    """Run a C++ solver, streaming its 'step X/Y' (or 't=…') output back as a live percent.

    `cancel` is a threading.Event (or None); when it is set the process is killed
    and `Cancelled` is raised. If not given, the event attached to the progress
    callback as `pr.cancel` is used (that is how `solve_exhibit` passes it down).
    The process is also killed if anything raises while it is being watched, so a
    cancelled or failed job never leaves a solver running in the background.
    """
    if cancel is None:
        cancel = getattr(pr, "cancel", None)
    if pr is None and cancel is None:
        subprocess.run(args, check=True, env=_ENV); return
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1, env=_ENV)
    tail = collections.deque(maxlen=40)                 # kept so a failure can quote the solver
    with _LIVE_LOCK:
        _LIVE_PROCS.add(proc)
    lines = queue.Queue()

    def reader():                       # pump stdout so polling for cancellation never blocks on I/O
        try:
            for line in proc.stdout:
                lines.put(line)
        finally:
            lines.put(None)
    threading.Thread(target=reader, daemon=True).start()

    last = -1
    try:
        while True:
            if cancel is not None and cancel.is_set():
                raise Cancelled()
            try:
                line = lines.get(timeout=0.2)
            except queue.Empty:
                continue
            if line is None:
                break
            tail.append(line)
            pct = None
            m = _STEP_RE.search(line)
            if m and int(m.group(2)):
                pct = int(m.group(1)) / int(m.group(2))
            elif tend:
                mt = _T_RE.search(line)
                if mt:
                    pct = float(mt.group(1)) / tend
            if pct is not None and pr is not None:
                p = max(0, min(99, int(pct * 100)))
                if p != last:
                    last = p; pr(f"simulating… {p}%")
        proc.wait()
    except BaseException:
        _kill(proc)
        raise
    finally:
        with _LIVE_LOCK:
            _LIVE_PROCS.discard(proc)
    if cancel is not None and cancel.is_set():
        raise Cancelled()
    if proc.returncode != 0:
        raise SolverError(proc.returncode, args, output="".join(tail))


class SolverError(subprocess.CalledProcessError):
    """A solver exited non-zero. Its own last words are kept, so the user is told what was
    rejected ("--tau must be in (0.5, 10]") instead of only "exit status 2"."""

    def reason(self):
        lines = [x.strip() for x in (self.output or "").splitlines() if x.strip()]
        for line in reversed(lines):                     # the solvers print "error: <what was wrong>"
            if line.lower().startswith("error:"):
                return line.split(":", 1)[1].strip()
        return lines[-1] if lines else ""

    def __str__(self):
        what = {2: "the solver rejected this setup", 3: "the solver could not write its output"}.get(
            self.returncode, "the solver stopped")
        r = self.reason()
        return f"{what}: {r} (exit code {self.returncode})" if r else f"{what} (exit code {self.returncode})"


def _bin(d, name):
    return SOLVERS / d / (name + EXE)


def _ensure(b):
    b = Path(b)
    frozen = sys.platform.startswith("win") or getattr(sys, "frozen", False)
    if frozen:
        if not b.exists():
            raise FileNotFoundError(f"solver not found: {b}. Build it first "
                                    f"(see docs/windows_build.md).")
        return
    # dev (source) build: (re)compile if the binary is missing OR the source is newer,
    # so running the app always picks up edited solver code — no stale binaries.
    src = b.with_suffix(".cpp")
    stale = b.exists() and src.exists() and src.stat().st_mtime > b.stat().st_mtime
    if not b.exists() or stale:
        subprocess.run(["make", "-C", str(b.parent)], check=True, env=_ENV)


from . import io as fio   # noqa: E402  (solver output readers live in one place)


def _read_vel(d, i, nx, ny):
    return fio.read_frame(d, i, nx, ny)


def _read_scalar(d, i, nx, ny):
    return fio.read_scalar(d, i, nx, ny)


def _nframes(d):
    return int(fio.read_meta(d)["nframes"])


RES = {"Low (fast)": 0.6, "Medium": 1.0, "High": 1.35, "Ultra (slow)": 1.8}
# Public view names. "Speed" is |u| (a scalar magnitude), never a vector field.
VIEWS = {"lbm": ["Vorticity", "Speed", "Streamlines"],
         "spectral": ["Vorticity", "Speed", "Streamlines"],
         "density": ["Schlieren", "Density", "Speed"],
         "ns": ["Dye", "Speed", "Vorticity", "Streamlines"],
         "particles": ["Particles", "Foam & spray", "Speed field"],
         "porous": ["Speed", "Streamlines", "Vorticity"],
         "field": ["Pattern"],
         "quantum": ["Probability |ψ|²", "Phase"],
         "tracer": ["Concentration", "Speed", "Streamlines"]}
_VIEW_ALIASES = {"Velocity": "Speed", "Velocity field": "Speed field"}   # pre-1.1 names
DEFCMAP = {"lbm": "Curl (cyan–amber)", "spectral": "Curl (cyan–amber)",
           "density": "Ember (fire)", "ns": "Ember (fire)", "particles": "Ocean (water)",
           "porous": "Turbo", "field": "Inferno", "quantum": "Magma", "tracer": "Inferno"}
# Views whose field is signed: always drawn with a zero-centred (symmetric) colour range.
SIGNED_VIEWS = {"Vorticity", "Phase"}


def _res(p):
    return RES.get(p.get("resolution", "Medium"), 1.0)


def _durv(p):
    return float(p.get("duration", 1.0))


class _LazyFields:
    """A per-frame derived field computed on first access (a one-frame preview does not
    derive the whole animation). Indexable and iterable like a list."""

    def __init__(self, n, fn):
        self._n, self._fn, self._d = n, fn, {}

    def __len__(self):
        return self._n

    def __getitem__(self, i):
        if isinstance(i, slice):
            return [self[j] for j in range(*i.indices(self._n))]
        i = i % self._n
        v = self._d.get(i)
        if v is None:
            v = self._d[i] = self._fn(i)
        return v

    def __iter__(self):
        for i in range(self._n):
            yield self[i]

    def nbytes(self):
        return sum(getattr(v, "nbytes", 0) for v in self._d.values())


# ---------- Result: holds raw fields, renders any view on demand ----------
class Result:
    """Solved fields + everything needed to render any view of them.

    raw   : list of per-frame arrays ([y, x] scalar, (ux, uy) tuple, or SPH particle rows)
    times : simulation time of every frame in `raw` (solver units; see hints["time_unit"])
    hints : solver metadata (grid spacing, velocity fields for scalar kinds, probe series …)

    Rendering is split in two cached stages so palette changes are cheap:
      derived(view)  -> per-view scalar fields + the shared colour normalisation (cached)
      iter_frames()  -> RGB frames one at a time (a generator; nothing is materialised)
    `render()` keeps the list-returning API for scripts and tests.
    """

    def __init__(self, kind, raw, info, mask=None, hints=None, times=None):
        self.kind, self.raw, self.info = kind, raw, info
        self.mask, self.hints = mask, (hints or {})
        self.times = list(times) if times is not None else list(self.hints.get("times", []))
        if len(self.times) != len(raw):
            self.times = [float(i) for i in range(len(raw))]
            self.hints.setdefault("time_unit", "frame")
        self._cache = {}

    @property
    def views(self):
        return VIEWS[self.kind]

    @property
    def nframes(self):
        return len(self.raw)

    def view_name(self, view):
        view = _VIEW_ALIASES.get(view, view)
        return view if view in self.views else self.views[0]

    def colormap(self, colormap):
        return render.COLORMAPS.get(colormap, render.COLORMAPS[DEFCMAP[self.kind]])

    # ----- stage 1: derived fields + normalisation (cached per view) -----
    def derived(self, view=None):
        view = self.view_name(view)
        d = self._cache.get(view)
        if d is None:
            d = self._cache[view] = self._derive(view)
        return d

    def cache_bytes(self):
        """Bytes held by the derived-field caches (counted by the run store)."""
        n = 0
        for d in self._cache.values():
            f = d.get("fields")
            if isinstance(f, _LazyFields):
                n += f.nbytes()
            elif isinstance(f, list):
                n += sum(getattr(x, "nbytes", 0) for x in f if not isinstance(x, np.memmap))
        return n

    def _vel(self):
        return self.raw if self.kind in ("lbm", "spectral", "porous") else self.hints.get("vel")   # tracer: steady field in hints

    def _derive(self, view):
        N = render.Norm
        if self.kind == "tracer" and view == "Concentration":
            c = self.raw
            vmax = float(np.percentile(c[0], 99.9)) or 1.0            # the injected level, not a late trace
            return {"fields": c, "norm": N(0, vmax, gamma=0.6), "label": self.hints.get("label", "tracer c/c₀"),
                    "mask_color": "#0f1830", "upscale": 1}
        if self.kind in ("lbm", "spectral", "porous", "ns", "tracer") and view in ("Speed", "Streamlines", "Vorticity"):
            vel = self._vel(); n = len(vel); dx = self.hints.get("dx", 1.0)
            if view == "Vorticity":
                f = _LazyFields(n, lambda i: render.vorticity(vel[i][0], vel[i][1], dx))
                v = float(np.percentile(np.abs(f[n - 1]), 99.0)) + 1e-12       # colour limits from the final frame only
                return {"fields": f, "norm": N(-v, v), "label": "vorticity ω",
                        "mask_color": render.SOLID, "upscale": 1}
            sp = _LazyFields(n, lambda i: np.sqrt(vel[i][0] * vel[i][0] + vel[i][1] * vel[i][1]))
            pct = 80.0 if self.kind in ("porous", "tracer") else 99.5   # pore flow is slow/sparse → brighten
            vmax = float(np.percentile(sp[n - 1], pct)) + 1e-12
            if view == "Streamlines":
                return {"fields": sp, "vel": vel, "norm": N(0, vmax), "label": "speed |u|"}
            g = 0.45 if self.kind in ("porous", "tracer") else 1.0
            mc = "#0f1830" if self.kind in ("porous", "tracer") else render.SOLID
            return {"fields": sp, "norm": N(0, vmax, gamma=g), "label": "speed |u|",
                    "mask_color": mc, "upscale": 1}
        if self.kind == "ns":                                           # Dye
            v0, v1 = self.hints["vlim"]
            return {"fields": self.raw, "norm": N(v0, v1, gamma=self.hints.get("gamma", 1.0)),
                    "label": self.hints.get("label", ""), "mask_color": "#6e6358", "upscale": 1}
        if self.kind == "density":
            h = self.hints; solid = h.get("solid")
            if view == "Speed":
                vel = h["vel"]; sp = _LazyFields(len(vel), lambda i: np.hypot(vel[i][0], vel[i][1]))
                ref = sp[len(vel) - 1] if solid is None else sp[len(vel) - 1][~solid]
                return {"fields": sp, "norm": N(0, float(np.percentile(ref, 99.0)) + 1e-9),
                        "label": "speed |u|", "upscale": 1}
            if view == "Density":
                return {"fields": self.raw, "norm": N(float(np.percentile(self.raw[-1], 1)),
                                                      float(np.percentile(self.raw[-1], 99.5)) + 1e-6),
                        "label": "density ρ", "upscale": 1}
            raw = self.raw; sch = _LazyFields(len(raw), lambda i: render.schlieren(raw[i]))
            sref = sch[len(raw) - 1] if solid is None else sch[len(raw) - 1][~solid]
            return {"fields": sch, "norm": N(0.0, float(np.percentile(sref, 99.5)) + 1e-6, gamma=0.7),
                    "label": "|∇ρ|", "upscale": 1}
        if self.kind == "particles":
            vmax = self.hints["vmax"]
            if view == "Speed field":
                return {"fields": _LazyFields(self.nframes, self._sph_field), "norm": N(0, vmax), "label": "speed |v|",
                        "upscale": 3}
            # particle shading floors at 0.34 so resting water stays visible; the legend uses the same floor
            return {"fields": None, "norm": N(0, vmax, floor=0.34 if view == "Particles" else 0.0),
                    "label": "speed |v|"}
        if self.kind == "field":
            return {"fields": self.raw, "norm": N(0, float(np.percentile(self.raw[-1], 99.0)) + 1e-9),
                    "label": self.hints.get("label", ""), "upscale": 2}
        if self.kind == "quantum":
            pmax = float(np.percentile(self.raw[-1], 99.7)) + 1e-12
            if view == "Phase":
                return {"fields": self.hints["phase"], "norm": N(-np.pi, np.pi), "label": "arg ψ", "pmax": pmax}
            return {"fields": self.raw, "norm": N(0, pmax), "label": "|ψ|²", "upscale": 2}
        raise ValueError(f"no view {view!r} for kind {self.kind!r}")

    def _sph_field(self, i):
        """Bin frame i's particles onto a grid: a smooth speed field, NaN where there is no water."""
        Lx, Ly = self.hints["Lx"], self.hints["Ly"]
        gx = 150; gy = max(40, int(gx * Ly / Lx))

        def blur(a, k=2):
            w = np.ones(2 * k + 1) / (2 * k + 1)
            for ax in (0, 1):
                a = np.apply_along_axis(lambda m: np.convolve(m, w, mode="same"), ax, a)
            return a
        d = self.raw[i]
        ix = np.clip((d[:, 0] / Lx * gx).astype(int), 0, gx - 1)
        iy = np.clip((d[:, 1] / Ly * gy).astype(int), 0, gy - 1)
        cnt = np.zeros((gy, gx)); ssum = np.zeros((gy, gx))
        np.add.at(cnt, (iy, ix), 1.0); np.add.at(ssum, (iy, ix), d[:, 2])
        bc = blur(cnt, 2)
        field = blur(ssum, 2) / (bc + 1e-6)
        field[bc < 0.05] = np.nan                          # empty (air) cells: no measurement, not zero
        return field

    # ----- stage 2: frames -----
    def render(self, view=None, colormap=None, vmin=None, vmax=None):
        """All frames of a view as a list (convenience for scripts/tests)."""
        return list(self.iter_frames(view, colormap, vmin, vmax))

    def frame(self, index, view=None, colormap=None, vmin=None, vmax=None):
        """One rendered frame (index may be negative or a float fraction in [0, 1])."""
        if isinstance(index, float) and 0.0 <= index <= 1.0:
            index = int(round(index * (self.nframes - 1)))
        index = int(index) % self.nframes
        for i, fr in enumerate(self.iter_frames(view, colormap, vmin, vmax, only=index)):
            return fr

    def iter_frames(self, view=None, colormap=None, vmin=None, vmax=None, only=None):
        """Yield RGB frames one at a time. `vmin`/`vmax` override the automatic colour
        range (manual limits); `only` renders a single frame index."""
        view = self.view_name(view); cm = self.colormap(colormap)
        d = self.derived(view); norm = d["norm"]
        if vmin is not None or vmax is not None:
            norm = norm.with_range(vmin, vmax)
        idx = range(self.nframes) if only is None else [only]
        if self.kind == "particles" and view != "Speed field":
            yield from self._iter_particles(cm, norm, foam=(view == "Foam & spray"), idx=idx)
            return
        if view == "Streamlines":
            for i in idx:
                ux, uy = d["vel"][i]
                yield render.add_colorbar(render.streamlines_rgb(ux, uy, cmap=cm, mask=self.mask, norm=norm),
                                          cm, norm, d["label"])
            return
        if self.kind == "quantum" and view == "Phase":
            import matplotlib.cm as mcm
            twil = mcm.get_cmap("twilight")
            for i in idx:
                hue = twil(norm(self.hints["phase"][i]))[..., :3]
                val = np.clip(self.raw[i] / d["pmax"], 0, 1)[..., None]
                yield render.add_colorbar(np.flipud((hue * val * 255).astype(np.uint8)), "twilight", norm, d["label"])
            return
        if self.kind == "density":
            yield from self._iter_density(view, cm, norm, d, idx)
            return
        fields = d["fields"]; up = d.get("upscale", 1); mc = d.get("mask_color", render.SOLID)
        for i in idx:
            f = fields[i]
            img = render.field_to_rgb(f, cm, norm, mask=self.mask, mask_color=mc, upscale=up)
            yield render.add_colorbar(img, cm, norm, d["label"], clip_frac=norm.clipped(f) if (i == idx[-1] or only is not None) else None)

    def _iter_density(self, view, cm, norm, d, idx):
        h = self.hints; deb = h.get("debris", 0); nx, ny = h.get("nx"), h.get("ny")
        solid = h.get("solid"); city = solid is not None
        failt = h.get("failt")                              # per-block failure fraction, -1=intact
        CONCRETE = np.array([78, 82, 102], np.uint8)
        n = self.nframes

        def standing(tau):
            if failt is None:
                return solid[::-1]
            return (solid & ((failt < 0) | (tau < failt)))[::-1]

        deb_state = None
        if deb and h.get("mode") == "blast" and view == "Schlieren":
            rng = np.random.default_rng(7)
            if city:
                fy_, fx_ = np.where(solid & (failt >= 0)) if failt is not None else np.where(solid)
                if len(fx_):
                    pick = rng.integers(0, len(fx_), deb)
                    bx = fx_[pick] + rng.uniform(-1, 1, deb); by = fy_[pick] + rng.uniform(-1, 1, deb)
                    flaunch = failt[fy_[pick], fx_[pick]] if failt is not None else np.zeros(deb)
                else:
                    bx = by = flaunch = np.zeros(0); deb = 0
                cx, cy = nx * 0.20, ny * 0.14
            else:
                bx = rng.uniform(0, nx, deb); by = rng.uniform(0, ny, deb)
                cx, cy = nx / 2, ny / 2; flaunch = None
            dist = np.hypot(bx - cx, by - cy) + 1e-6; ang = np.arctan2(by - cy, bx - cx)
            if city:
                ang += rng.uniform(-0.4, 0.4, deb)
            push = rng.uniform(0.5, 1.0, deb); Rmax = 0.75 * np.hypot(nx, ny) / 2
            deb_state = (bx, by, flaunch, dist, ang, push, Rmax)
        for fi in idx:
            tau = fi / max(1, n - 1)
            f = d["fields"][fi]
            img = np.array(render.field_to_rgb(f, cm, norm, upscale=1))
            if city:
                img[standing(tau)] = CONCRETE
            if deb_state is not None and deb:
                bx, by, flaunch, dist, ang, push, Rmax = deb_state
                since = (tau - flaunch) if city else (tau - dist / (Rmax * 1.25))
                disp = np.where(since > 0, since * Rmax * 1.25 * push * 0.7, 0.0)
                px = bx + np.cos(ang) * disp; py = by + np.sin(ang) * disp
                if city:
                    py = py + np.where(since > 0, since * Rmax * 0.9 - (since ** 2) * Rmax * 2.2, 0.0)
                iy = ny - 1 - py
                heat = np.clip(np.where(since > 0, np.exp(-2.2 * since), 0.12), 0.08, 1.0)
                size = 1.0 + 1.8 * heat
                keep = (since > 0) & (px > 1) & (px < nx - 1) & (iy > 1) & (iy < ny - 1)
                img = render.overlay_particles(img, px[keep], iy[keep], size[keep], heat[keep])
            yield render.add_colorbar(img, cm, norm, d["label"])

    def _iter_particles(self, cm, norm, foam=False, idx=None):
        Lx, Ly, vmax = self.hints["Lx"], self.hints["Ly"], self.hints["vmax"]
        hull = self.hints.get("hull")
        dp = self.hints.get("dp", 0.04); DPI = 110
        px_per_unit = 6.4 * DPI / Lx
        diam_pt = dp * px_per_unit / (DPI / 72.0)
        PSIZE = float(np.clip((diam_pt * 1.35) ** 2, 5.0, 230.0))
        for fi in idx:
            d = self.raw[fi]
            with render._MPL_LOCK:
                fig, ax = render.reuse_figure(("sph", round(Ly / Lx, 4)), (6.4, 6.4 * Ly / Lx), DPI)
                ax.cla(); ax.set_facecolor(render.INK); fig.patch.set_facecolor(render.INK)
                sp = np.clip(d[:, 2] / vmax, 0, 1)
                if foam:
                    ax.scatter(d[:, 0], d[:, 1], c="#173a6b", s=PSIZE, edgecolors="none")
                    fast = sp > 0.45
                    if fast.any():
                        ax.scatter(d[fast, 0], d[fast, 1], c="white", s=PSIZE * 0.7,
                                   alpha=np.clip(sp[fast], 0.3, 0.95), edgecolors="none")
                else:
                    ax.scatter(d[:, 0], d[:, 1], c=norm(d[:, 2]), cmap=cm, vmin=0.0, vmax=1.0,
                               s=PSIZE, edgecolors="none")
                if hull is not None:
                    hp = hull[fi]; ax.scatter(hp[:, 0], hp[:, 1], c="#c79a5b", s=PSIZE, edgecolors="none")
                ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
                rgb = render.figure_rgb(fig)
            yield rgb if foam else render.add_colorbar(rgb, cm, norm, "speed |v|")

    # ----- disk backing for large results -----
    def spill(self, directory):
        """Move the frame arrays to memory-mapped .npy files under `directory`, so a
        large run costs disk instead of RAM while it sits in the history. Arrays keep
        their shapes/dtypes (they become read-only memmap views); the derived-field
        cache is cleared so it is rebuilt from disk on demand. Returns bytes moved.
        Particle results (ragged frames) are stored one file per frame."""
        directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
        moved = 0

        def _dump(name, frames):
            nonlocal moved
            if not frames:
                return frames
            f0 = frames[0]
            if isinstance(f0, tuple):                                   # (ux, uy) pairs
                ncomp = len(f0); mm = []
                for ci in range(ncomp):
                    path = directory / f"{name}_{ci}.npy"; a0 = np.asarray(f0[ci])
                    m = np.lib.format.open_memmap(path, mode="w+", dtype=a0.dtype, shape=(len(frames),) + a0.shape)
                    for i, fr in enumerate(frames):                     # one frame at a time: no stacked copy
                        m[i] = fr[ci]; moved += a0.nbytes
                    m.flush(); del m
                    mm.append(np.load(path, mmap_mode="r"))
                return [tuple(mm[ci][i] for ci in range(ncomp)) for i in range(len(frames))]
            if all(getattr(f, "shape", None) == f0.shape for f in frames):
                path = directory / f"{name}.npy"; a0 = np.asarray(f0)
                m = np.lib.format.open_memmap(path, mode="w+", dtype=a0.dtype, shape=(len(frames),) + a0.shape)
                for i, fr in enumerate(frames):
                    m[i] = fr; moved += a0.nbytes
                m.flush(); del m
                mm = np.load(path, mmap_mode="r")
                return [mm[i] for i in range(len(frames))]
            out = []                                                    # ragged (particles)
            for i, f in enumerate(frames):
                path = directory / f"{name}_{i:05d}.npy"; np.save(path, f); moved += f.nbytes
                out.append(np.load(path, mmap_mode="r"))
            return out

        self.raw = _dump("raw", self.raw)
        if isinstance(self.hints.get("vel"), list):
            self.hints["vel"] = _dump("vel", self.hints["vel"])
        self._cache.clear()
        self.hints["spilled_to"] = str(directory)
        return moved

    # ----- metadata -----
    def meta(self):
        """JSON-safe description of this result (see docs/result_schema.md)."""
        h = self.hints
        shape = None
        if self.raw:
            f0 = self.raw[0]
            arr = f0[0] if isinstance(f0, tuple) else f0
            shape = list(getattr(arr, "shape", []))
        def scal(v):
            return float(v) if isinstance(v, (np.floating, np.integer)) else v
        return {"kind": self.kind, "info": self.info, "views": list(self.views), "frames": self.nframes,
                "shape": shape, "times": [float(t) for t in self.times],
                "time_unit": h.get("time_unit", "solver units"),
                "warmup_dropped": h.get("warmup_dropped"),
                "effective": {k: scal(v) for k, v in (h.get("effective") or {}).items()
                              if isinstance(v, (int, float, str, bool, np.floating, np.integer))},
                "hints": {k: scal(v) for k, v in h.items()
                          if isinstance(v, (int, float, str, bool, np.floating, np.integer))}}


# ---------- parameter descriptors (pre-run only) ----------
# Keys: see flowzoo/schema.py. min/max = recommended range; hard_min/hard_max = solver
# limits; units; advanced (hidden in the approachable mode); fixed (what stays fixed).
def P_RES(help="Grid resolution. Changes only the grid: the domain, parameters and simulated "
               "interval stay the same, so results at different resolutions are comparable."):
    return {"name": "resolution", "label": "Resolution", "type": "choice",
            "choices": list(RES), "default": "Medium", "group": "Render", "help": help}


def P_DUR(help="Simulated interval as a multiple of the scene's reference interval (1.0 = default)."):
    return {"name": "duration", "label": "Duration (×)", "type": "float", "default": 1.0,
            "min": 0.2, "max": 6.0, "hard_min": 0.05, "hard_max": 20.0, "group": "Render", "help": help}


def _f(name, label, default, lo, hi, group, help, units=None, hard_min=None, hard_max=None,
       advanced=False, fixed=None):
    d = {"name": name, "label": label, "type": "float", "default": default,
         "min": lo, "max": hi, "group": group, "help": help}
    if units: d["units"] = units
    if hard_min is not None: d["hard_min"] = hard_min
    if hard_max is not None: d["hard_max"] = hard_max
    if advanced: d["advanced"] = True
    if fixed: d["fixed"] = fixed
    return d


def _i(name, label, default, lo, hi, group, help, units=None, hard_min=None, hard_max=None,
       advanced=False, fixed=None):
    d = _f(name, label, int(default), lo, hi, group, help, units, hard_min, hard_max, advanced, fixed)
    d["type"] = "int"
    return d


def _when(qd, ctrl, vals):
    # mark a descriptor so the app only shows it when control `ctrl` ∈ vals
    qd = dict(qd); qd["when"] = (ctrl, vals); return qd


_H = {
    "Re": "Reynolds number Re = U·D/ν (inertia ÷ viscosity) with D the reference length below. "
          "Low → smooth steady flow; high → vortex shedding and turbulence.",
    "U": "Inlet flow speed in lattice units. The Reynolds number is held fixed: the viscosity is "
         "recomputed as ν = U·D/Re, so a higher speed means a higher lattice Mach number "
         "(keep ≲ 0.15) and a shorter physical time per step, not a stronger wake.",
    "visc": "Kinematic viscosity ν — how 'thick' the fluid is. Lower → finer, more chaotic "
            "structures; higher → smoother, damped flow.",
    "buoy": "Buoyancy coefficient: force per unit of the transported scalar (dye/temperature). "
            "Higher → a faster, more vigorous plume.",
    "conf": "Vorticity confinement — re-injects small-scale swirl lost to numerical "
            "diffusion (a modelling knob, not a physical property). 0 = none.",
    "grav": "Gravity driving the instability. Higher → faster fingering / collapse.",
}


# ---------- effective configuration (the numbers the solver will actually use) ----------
def _wt_config(p):
    """Wind tunnel: grid, reference length, τ/ν and step count. nx, ny, D and the step count
    scale with the resolution setting, so the elapsed convective time U·steps/D is the same
    only when the duration is scaled too — the derived readouts say so."""
    s = _res(p); nx, ny = int(900 * s), int(300 * s)
    Re = float(p["reynolds"]); U = float(p["speed"]); obs = p["obstacle"]
    D = max(8.0, ny * float(p["size"]))
    if obs == "Your text":
        D = ny * 0.34
    elif obs == "F1 car":
        D = 0.34 * ny * 1.05
    elif obs == "Cyclist":
        D = 0.6 * ny * 0.42
    elif obs == "Peloton (drafting)":
        D = 0.6 * ny * 0.38
    tau = 0.5 + 3 * (U * D / Re); steps = int(44000 * _durv(p))
    return {"nx": nx, "ny": ny, "Re": Re, "U": U, "D": D, "tau": tau, "nu": (tau - 0.5) / 3.0, "steps": steps,
            "save_every": max(1, steps // 120), "convective_time": U * steps / D, "mach": U * 3 ** 0.5}


def _porous_config(p):
    s = _res(p); nx, ny = int(380 * s), int(360 * s)
    grain = max(4, int(float(p["grain"]) * ny)); tau = 0.8
    force = 1.2e-5 * float(p.get("strength", 1.0))
    fdir = 1 if str(p.get("direction", "x")).lower().startswith("y") else 0
    steps = int(24000 * _durv(p))
    return {"nx": nx, "ny": ny, "grain": grain, "tau": tau, "nu": (tau - 0.5) / 3.0, "force": force, "fdir": fdir,
            "steps": steps, "save_every": max(1, steps // 120), "seed": int(p.get("seed", 1))}


def _tracer_config(p):
    """The porous sample, plus what the tracer needs. The molecular diffusivity follows from the
    Péclet number the user sets: Pe = u_pore · d_grain / D_m, with u_pore the pore-average speed
    measured by the flow itself (filled in by the runner, which knows it only after the flow has
    settled; `pe` and the geometry are what this function fixes)."""
    c = dict(_porous_config(p))
    c["pe"] = float(p.get("peclet", 20.0))
    c["injection"] = "pulse" if str(p.get("injection", "Continuous supply")).lower().startswith("pul") else "continuous"
    c["pulse_width"] = 0.06
    c["tracer_frames"] = 110
    return c


def _ns_config(mode, p):
    s = _res(p); steps = int(4800 * _durv(p))
    dims = {"smoke": (280, 440), "rt": (280, 440), "rb": (480, 230), "flame": (190, 360), "wind": (540, 420)}[mode]
    nx, ny = int(dims[0] * s), int(dims[1] * s)
    return {"nx": nx, "ny": ny, "steps": steps, "save_every": max(1, steps // 110), "dt": 1.0}


def _sph_config(p):
    sc = _SPLASH_SCENE.get(p.get("scene", "Dam break"), "dam"); Lx, Ly = _SPLASH_TANK[sc]
    if sc == "drop":
        a = float(p.get("dropsize", 0.4))
    elif sc == "pour":                                          # the glass is 0.13 m wide: the dam-break
        a = float(np.clip(2.0 * float(p.get("spout", 0.045)) * Lx, 0.01 * Lx, Lx))   # width would not fit
    else:
        a = float(p["width"])
    g = float(p["gravity"]); npart = max(500.0, float(p["particles"]))
    if sc == "pour":
        H = Ly; dp = Lx / 44.0; tend = 3.0 * _durv(p)
    else:
        H = float(p["height"]); dp = float(np.clip(np.sqrt(Lx * Ly * 0.4 / npart), 0.02, 0.08)); tend = 2.0 * _durv(p)
    Href = max(H, Ly * 0.5)                                     # the solver's reference height for c0
    c0 = 10.0 * (g * Href) ** 0.5; dt = 0.08 * 1.3 * dp / c0
    steps_est = tend / dt
    return {"scene": sc, "Lx": Lx, "Ly": Ly, "a": a, "H": H, "Href": Href, "g": g, "dp": dp, "tend": tend, "c0": c0,
            "dt": dt, "steps_est": int(steps_est), "save_every": max(20, int(steps_est // 120))}


def _spectral_config(p, mixing=False):
    s = _res(p); n = int(256 * s); L = 2 * np.pi; n0 = 256
    T_end = (2600 if mixing else 2800) * _durv(p) * 0.4 * (L / n0)
    dt = 0.4 * (L / n); steps = max(1, int(round(T_end / dt)))
    return {"n": n, "L": L, "dt": dt, "T_end": T_end, "steps": steps, "nu": 4e-4 if mixing else float(p["viscosity"])}


_NS_MODES = {"Rising Smoke": "smoke", "Candle Flame": "flame", "Mushroom Clouds": "rt", "Rayleigh-Benard": "rb",
             "Chimney Plume": "wind"}


def effective(name, params):
    """Resolved configuration for an exhibit (defaults filled): the same numbers the runner
    passes to the solver. Used by the derived readouts, result metadata and reports."""
    spec = EXHIBITS[name]
    p = {q["name"]: q["default"] for q in spec["params"]}; p.update(params or {})
    if name == "Wind Tunnel":
        return _wt_config(p)
    if name == "Porous Flow":
        return _porous_config(p)
    if name == "Tracer in Rock":
        return _tracer_config(p)
    if name in _NS_MODES:
        return _ns_config(_NS_MODES[name], p)
    if name == "The Big Splash":
        return _sph_config(p)
    if name == "Cloud Billows":
        return _spectral_config(p)
    if name == "Ink in Motion":
        return _spectral_config(p, mixing=True)
    return {}


def _thin(indices, keep):
    """Every k-th index of `indices` so that at most ~`keep` remain, always including the last one."""
    idx = list(indices)
    if len(idx) <= keep:
        return idx
    stride = max(1, (len(idx) - 1) // (keep - 1))
    out = idx[::stride]
    if out[-1] != idx[-1]:
        out.append(idx[-1])
    return out


# ---------- runners (SOLVE → raw fields) ----------
def _solve_windtunnel(p, pr, tmp):
    cfg = _wt_config(p); nx, ny = cfg["nx"], cfg["ny"]
    Re = float(p["reynolds"]); U = float(p["speed"]); obs = p["obstacle"]
    cx, cy = int(nx * float(p.get("xpos", 0.25))), ny // 2 + 2
    D = max(8.0, ny * float(p["size"]))                     # characteristic length
    if obs == "Your text":
        mask = geometry.text(nx, ny, p["text"], font_frac=0.34, x_frac=0.28, max_w_frac=0.5)
        D = ny * 0.34; probe = int(nx * 0.6)
    elif obs == "Square":
        mask = geometry.square(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    elif obs == "Diamond":
        mask = geometry.diamond(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    elif obs == "Airfoil":
        mask = geometry.airfoil(nx, ny, cx, cy, chord=D * 2.6, aoa_deg=float(p["angle"]))
        probe = cx + int(3 * D)
    elif obs == "F1 car":
        L = ny * 1.05; cx = int(nx * 0.30)
        mask = geometry.f1_car(nx, ny, cx, L); D = 0.34 * L; probe = cx + int(2.4 * L)
    elif obs == "Cyclist":
        S = ny * 0.42; cx = int(nx * 0.24)
        mask = geometry.cyclist(nx, ny, cx, S, riders=1); D = 0.6 * S; probe = cx + int(3 * S)
    elif obs == "Peloton (drafting)":
        S = ny * 0.38; cx = int(nx * 0.28)
        mask = geometry.cyclist(nx, ny, cx, S, riders=2, gap=1.0); D = 0.6 * S; probe = cx + int(3 * S)
    else:                                                   # Cylinder
        mask = geometry.cylinder(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    tau = cfg["tau"]
    probe = int(min(probe, 0.85 * nx))                      # keep the probe clear of the outlet sponge (last 12%)
    _ys = np.where(mask.any(axis=1))[0]                      # sample the wake at the body's height
    probe_y = int(round(_ys.mean())) if len(_ys) else ny // 2
    probe_y = int(np.clip(probe_y, 2, ny - 3))
    if obs in ("F1 car", "Cyclist", "Peloton (drafting)"):  # a real no-slip road under the vehicle
        mask[0:max(2, ny // 28), :] = 1                     # (otherwise periodic walls let flow wrap under)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    _ensure(_bin("lbm", "lbm2d"))
    steps = cfg["steps"]; save_every = cfg["save_every"]
    pr(f"LBM wind tunnel · {obs} · {nx}×{ny}, Re={Re:.0f}, {steps} steps…")
    _run_solver([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                 "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                 "--steps", str(steps), "--save_every", str(save_every),
                 "--out", tmp, "--probe_x", str(min(probe, nx - 2)), "--probe_y", str(probe_y)], pr)
    n = _nframes(tmp); all_t = fio.read_frame_times(tmp) or [float(i * save_every) for i in range(n)]
    use = _thin(range(n // 5, n), 90)                       # warm-up (first 20 %) dropped; final frame always kept
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    times = [all_t[i] for i in use]                         # lattice time steps of each kept frame
    hints = {"probe_x": min(probe, nx - 2), "probe_y": probe_y, "D": D, "U": U, "tau": tau,
             "nu": (tau - 0.5) / 3.0, "obstacle": obs,   # so diagnostics can pick the right plot
             "frame_dt_steps": (use[1] - use[0]) * save_every if len(use) > 1 else save_every,
             "time_unit": "lattice steps", "steps": steps, "dx": 1.0,
             "warmup_dropped": {"frames": n // 5, "until_time": all_t[n // 5] if n > n // 5 else None},
             "convective_time": cfg["convective_time"], "effective": cfg}
    probe_csv = Path(tmp) / "probe.csv"
    if probe_csv.exists():                                 # high-rate wake probe (every step)
        try:
            pv = np.loadtxt(probe_csv, delimiter=",", skiprows=1)
            if pv.ndim == 2 and len(pv):
                hints["probe_t"] = pv[:, 0].astype(np.float32); hints["probe_uy"] = pv[:, 1].astype(np.float32)
        except Exception:
            pass
    return Result("lbm", raw, f"wind tunnel · {obs} · Re={Re:.0f} · {nx}×{ny}",
                  mask=mask, hints=hints, times=times)


def _solve_porous(p, pr, tmp):
    cfg = _porous_config(p); nx, ny = cfg["nx"], cfg["ny"]
    phi = float(p["porosity"]); grain = cfg["grain"]
    mask = geometry.porous(nx, ny, solid_frac=1.0 - phi, grain=grain, seed=cfg["seed"])
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    _ensure(_bin("lbm", "lbm2d"))
    tau, force, fdir, steps = cfg["tau"], cfg["force"], cfg["fdir"], cfg["steps"]
    pr(f"LBM porous medium · φ={phi:.2f} · {nx}×{ny} · force along {'y' if fdir else 'x'}…")
    _run_solver([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                 "--mask", str(Path(tmp) / "m.bin"), "--periodic", "1", "--U", "0", "--force", str(force),
                 "--fdir", str(fdir), "--tau", str(tau), "--steps", str(steps), "--save_every", str(cfg["save_every"]),
                 "--out", tmp], pr)                                       # --U 0: the fluid really starts at rest
    n = _nframes(tmp); all_t = fio.read_frame_times(tmp) or [float(i * cfg["save_every"]) for i in range(n)]
    use = _thin(range(n // 3, n), 70)
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    times = [all_t[i] for i in use]
    meta = fio.read_meta(tmp)
    poro = meta.get("porosity", phi); perm = meta.get("permeability", 0.0)
    # convergence record: k at every saved frame → settled if the last 10 % of the run changed k by < 1 %
    kh = np.zeros((0, 2))
    try:
        kh = np.loadtxt(Path(tmp) / "perm.csv", delimiter=",", skiprows=1)
        kh = kh.reshape(-1, 2) if kh.size else np.zeros((0, 2))
    except Exception:
        pass
    settled, k_change = False, None
    if len(kh) >= 4:
        k_end = kh[-1, 1]; k_prev = kh[max(0, int(0.9 * len(kh)) - 1), 1]
        k_change = float(abs(k_end - k_prev) / (abs(k_end) + 1e-30)); settled = k_change < 0.01
    upore = meta.get("mean_ux_pore") or 0.0; re_pore = abs(upore) * grain / cfg["nu"]
    hints = {"porosity": poro, "permeability": perm, "grain": grain, "force": force, "tau": tau,
             "direction": "y" if fdir else "x", "seed": cfg["seed"],
             "nu": cfg["nu"], "mean_ux_pore": upore, "mean_ux": meta.get("mean_ux"),
             "k_status": "settled" if settled else "transient", "k_change_last10pct": k_change,
             "k_history_step": kh[:, 0].tolist() if len(kh) else [], "k_history": kh[:, 1].tolist() if len(kh) else [],
             "re_pore": re_pore, "time_unit": "lattice steps", "steps": steps, "dx": 1.0,
             "warmup_dropped": {"frames": n // 3, "until_time": all_t[n // 3] if n > n // 3 else None}, "effective": cfg}
    tag = "k" if settled else "k (transient)"
    return Result("porous", raw, f"porous · φ={poro:.2f} · {tag}_{'y' if fdir else 'x'}={perm:.2e}", mask=mask, hints=hints, times=times)


def _solve_tracer(p, pr, tmp):
    """Settle the pore flow, then carry a tracer through it (advection + diffusion).

    The flow is solved exactly as the porous experiment solves it, and the settled velocity field
    is then held fixed while the tracer crosses: at these pore Reynolds numbers (far below one)
    the flow does not change over that time, so this is exact rather than a shortcut. Only
    molecular diffusion enters the transport step; the spreading that the plume shows comes out
    of the velocity field itself.
    """
    from . import transport
    cfg = _tracer_config(p)
    flow = _solve_porous(p, pr, tmp)                     # same sample, same driving force
    ux, uy = flow.raw[-1]                                # the settled field
    solid = np.asarray(flow.mask, bool)
    fluid = ~solid
    speed = np.sqrt(ux * ux + uy * uy)
    u_pore = float(speed[fluid].mean()) if fluid.any() else 0.0
    grain = float(cfg["grain"])
    pe = max(1e-3, float(cfg["pe"]))
    dm = max(1e-9, u_pore * grain / pe) if u_pore > 0 else 1e-4
    axis = "y" if cfg["fdir"] else "x"
    length = (solid.shape[1] if axis == "x" else solid.shape[0])
    u_adv = float(np.abs(ux if axis == "x" else uy)[fluid].mean()) or u_pore or 1e-6
    t_cross = length / max(u_adv, 1e-9)                  # one pore-volume crossing
    dt_est = transport.Transport(ux, uy, solid, dm, axis=axis).dt
    steps = int(np.clip(t_cross * 1.2 * _durv(p) / dt_est, 200, 60000))
    pr(f"tracer · Pe={pe:g} · D_m={dm:.2e} · {steps} steps…")
    frames, times, rec = transport.run(ux, uy, solid, dm, axis=axis, injection=cfg["injection"],
                                       steps=steps, nframes=cfg["tracer_frames"],
                                       pulse_width=cfg["pulse_width"],
                                       progress=lambda f: pr(f"tracer… {int(100 * f)}%"))
    vel = [(ux, uy)] * len(frames)                       # one steady field, shared by every frame
    hints = {"label": "tracer c/c₀", "vel": vel, "dx": 1.0, "time_unit": "lattice steps",
             "peclet": pe, "dm": dm, "u_pore": u_pore, "u_adv": u_adv, "grain": grain,
             "axis": axis, "injection": cfg["injection"], "length_cells": length,
             "porosity": flow.hints.get("porosity"), "permeability": flow.hints.get("permeability"),
             "k_status": flow.hints.get("k_status"), "pore_volume_cells": rec["pore_volume"],
             "t_cross": t_cross, "effective": cfg, **{k: rec[k] for k in
             ("breakthrough", "outlet_slab_mean", "centre_cells", "variance_cells2", "mass",
              "mass_out", "mass_in", "balance", "mass_initial", "dt", "u_max", "numerical_diffusion")}}
    inj = "steady supply" if cfg["injection"] == "continuous" else "pulse"   # open outlet: tracer leaves
    info = f"tracer · {inj} · Pe={pe:g} · φ={flow.hints.get('porosity', 0):.2f}"
    return Result("tracer", frames, info, mask=solid, hints=hints, times=times)


def _solve_ns(mode, p, pr, tmp):
    cfg = _ns_config(mode, p); nx, ny, steps = cfg["nx"], cfg["ny"], cfg["steps"]
    _ensure(_bin("incompressible", "ins2d"))
    args = [str(_bin("incompressible", "ins2d")), "--mode", mode, "--nx", str(nx),
            "--ny", str(ny), "--steps", str(steps), "--save_every", str(cfg["save_every"]),
            "--out", tmp, "--visc", str(p["viscosity"])]
    if mode == "smoke":
        args += ["--buoy", str(p["buoyancy"]), "--conf", str(p["confinement"]), "--srcw", str(p["source"]),
                 "--flicker", str(p.get("flicker", 0.0))]
        hints = {"vlim": (0.0, 0.85), "gamma": 0.85, "label": "smoke density"}
    elif mode == "rt":
        args += ["--grav", str(p["gravity"]), "--pert", str(p["perturbation"]), "--conf", "0",
                 "--iters", "80", "--atwood", str(p.get("atwood", 1.0)), "--modes", str(int(p.get("modes", 0)))]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "density ρ"}
    elif mode == "rb":
        args += ["--buoy", str(p["buoyancy"]), "--conf", "0", "--iters", "80",
                 "--pert", str(p.get("perturbation", 1.0)), "--kappa", str(p.get("kappa", 0.02))]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "temperature T", "kappa": float(p.get("kappa", 0.02))}
    elif mode == "flame":                           # laminar diffusion flame (Burke–Schumann)
        args += ["--buoy", str(p["buoyancy"]), "--zst", str(p.get("zst", 0.12)),
                 "--conf", str(p["confinement"]), "--srcw", str(p["source"]), "--visc", str(p["viscosity"])]
        hints = {"vlim": (0.0, 1.0), "gamma": 0.6, "label": "flame temperature T"}
    else:                                           # wind — chimney plume in a crosswind
        args += ["--buoy", str(p["buoyancy"]), "--wind", str(p["wind"]),
                 "--conf", str(p["confinement"]), "--srcw", str(p["source"])]
        hints = {"vlim": (0.0, 0.85), "gamma": 0.85, "label": "smoke density"}
    pr(f"Navier–Stokes ({mode}) {nx}×{ny}, {steps} steps…")
    _run_solver(args, pr)
    n = _nframes(tmp); idx = _thin(range(n), 100)
    raw = [_read_scalar(tmp, i, nx, ny) for i in idx]
    all_t = fio.read_frame_times(tmp) or [float(i * cfg["save_every"]) for i in range(n)]
    times = [all_t[i] for i in idx]                          # solver steps (dt = 1 in ins2d)
    hints["vel"] = [fio.read_frame(tmp, i, nx, ny, prefix="vel") for i in idx]   # for Speed/Vorticity/Streamlines
    hints["ns_mode"] = mode                                  # so diagnostics can pick the right plot
    hints.update({"time_unit": "solver steps (dt = 1)", "steps": steps, "dx": 1.0, "nu": float(p["viscosity"]),
                  "effective": cfg})
    mask = None
    if mode == "wind":                                       # draw the solid chimney stack
        stack_h = int(0.32 * ny); sxx = nx // 4
        sw = max(6, int(nx / 12 * float(p["source"]))); hw = max(2, sw // 2)
        mask = np.zeros((ny, nx), np.uint8)
        mask[0:stack_h, max(0, sxx - hw):min(nx, sxx + hw + 1)] = 1
    return Result("ns", raw, f"{mode}  {nx}×{ny}", hints=hints, mask=mask, times=times)


def _solve_euler(mode, p, pr, tmp):
    s = _res(p)
    if mode == "sod":
        nx, ny = int(600 * s), 24; tend = 0.2 * nx * float(p.get("tend", 1.0)) * _durv(p)   # code time 0.2·nx per unit tube length
        extra = []
        hints = {"mode": "sod", "nx": nx, "ny": ny, "tube_length": 1.0}
    elif mode == "blast":
        nx = ny = int(420 * s); tend = 70 * _durv(p)
        bld = 1 if p.get("scene") == "Shock hits a city" else 0
        p_amb = 0.1                                        # ambient pressure in the solver's code units
        extra = ["--p0", str(float(p["pressure"]) * p_amb), "--radius", str(p["charge"]), "--building", str(bld)]
        if bld:
            erodes = str(p.get("structure", "Rigid walls")).startswith("Erodes")
            extra += ["--strength", str(p.get("strength", 1.0) if erodes else 1e9)]   # 1e9: never fails = rigid
        hints = {"mode": "blast", "debris": int(p.get("debris", 0)), "nx": nx, "ny": ny,
                 "building": bld, "p_ambient": p_amb, "p0": float(p["pressure"]) * p_amb,
                 "pressure_ratio": float(p["pressure"]), "structure": p.get("structure", "Rigid walls") if bld else None}
    else:
        nx, ny = int(620 * s), int(320 * s); tend = 230 * _durv(p)
        nb = 2 if p.get("target") == "Two bubbles" else 1
        rho_b = float(p.get("densratio", 0.18)); mach = float(p.get("mach", 1.5))
        extra = ["--bubr", str(p["bubble"]), "--bubrho", str(rho_b), "--nbub", str(nb),
                 "--mach", str(mach)]
        hints = {"mode": "bubble", "nx": nx, "ny": ny}
    _ensure(_bin("compressible", "euler2d"))
    pr(f"compressible Euler ({mode}) {nx}×{ny}…")
    _run_solver([str(_bin("compressible", "euler2d")), "--mode", mode, "--nx", str(nx),
                 "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4", "--steps", "200000",
                 "--save_every", "12", "--out", tmp] + extra, pr, tend=tend)
    n = _nframes(tmp); idx = _thin(range(n), 100)
    raw = [_read_scalar(tmp, i, nx, ny) for i in idx]
    meta_e = fio.read_meta(tmp)
    hints.update({"pmin": meta_e.get("pmin"), "rhomin": meta_e.get("rhomin")})
    ft = Path(tmp) / "frame_times.txt"                       # actual (adaptive-dt) time of every saved frame
    all_t = [float(x) for x in ft.read_text().split()] if ft.exists() else []
    times = [all_t[i] for i in idx] if len(all_t) >= n else [float(i) for i in idx]
    hints.update({"time_unit": "code units (ρ=1, p=1 ambient; c = √γ)" if len(all_t) >= n else "frame",
                  "tend": tend, "dx": 1.0 / nx})

    if (Path(tmp) / f"vel_{idx[0]:05d}.bin").exists():
        hints["vel"] = [fio.read_frame(tmp, i, nx, ny, prefix="vel") for i in idx]
    sp = Path(tmp) / "solid.bin"
    if sp.exists():
        hints["solid"] = np.fromfile(sp, dtype=np.float32).reshape(ny, nx) > 0.5
    fp = Path(tmp) / "failt.bin"
    if fp.exists():
        hints["failt"] = np.fromfile(fp, dtype=np.float32).reshape(ny, nx)   # [0,1], -1=intact
    return Result("density", raw, f"{mode}  {nx}×{ny}", hints=hints, times=times)


_SPLASH_SCENE = {"Dam break": "dam", "Drop & splash": "drop", "Sloshing tank": "slosh",
                 "Pour into a glass": "pour", "Wave tank": "waves", "Ship on waves": "ship",
                 "Still water (hydrostatic)": "rest", "Wavy ocean": "waves"}
_SPLASH_TANK = {"dam": (5.0, 3.2), "drop": (5.0, 3.2), "slosh": (5.0, 3.2), "rest": (5.0, 3.2),
                "pour": (0.13, 0.20), "waves": (6.0, 2.4), "ship": (6.0, 2.4)}   # pour = a real glass


def _solve_dam(p, pr, tmp):
    cfg = _sph_config(p)
    sc, Lx, Ly, a, H, g, dp, tend = cfg["scene"], cfg["Lx"], cfg["Ly"], cfg["a"], cfg["H"], cfg["g"], cfg["dp"], cfg["tend"]
    save_every = cfg["save_every"]                    # ~120 frames whatever the scene scale
    args = [str(_bin("sph", "sph2d")), "--scene", sc, "--a", str(a), "--H", str(H),
            "--Lx", str(Lx), "--Ly", str(Ly), "--dp", str(dp), "--g", str(g),
            "--tend", str(tend), "--save_every", str(save_every), "--out", tmp]
    if sc == "drop":
        args += ["--dh", str(p.get("dropheight", 0.70))]
    elif sc == "slosh":
        args += ["--sloshA", str(p.get("sloshA", 0.7)), "--sloshT", str(p.get("sloshT", 1.1))]
    elif sc == "pour":
        args += ["--sw", str(p.get("spout", 0.045)), "--pourv", str(p.get("pourv", 2.2))]
    elif sc in ("waves", "ship"):
        args += ["--waveA", str(p.get("waveA", 0.4)), "--waveT", str(p.get("waveT", 0.9))]
        if sc == "ship":
            args += ["--shipsz", str(p.get("shipsz", 1.0))]
    _ensure(_bin("sph", "sph2d"))
    pr(f"SPH · {p.get('scene', 'Dam break')} · dp={dp:.3f}…")
    _run_solver(args, pr)
    n = _nframes(tmp); idx = _thin(range(n), 100)
    raw = [np.fromfile(Path(tmp) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3) for i in idx]
    ft = Path(tmp) / "frame_times.txt"
    all_t = [float(x) for x in ft.read_text().split()] if ft.exists() else []
    times = [all_t[i] for i in idx] if len(all_t) >= n else [float(i) for i in idx]
    meta_s = fio.read_meta(tmp)
    if sc == "pour":          # colour by the pour/impact speed, not a dam-height scale
        vmax = 1.3 * max(float(p.get("pourv", 1.4)), float(np.sqrt(2 * g * Ly)))
    else:
        vmax = 1.2 * float(np.sqrt(2 * g * max(H, Ly * 0.5)))
    hints = {"Lx": Lx, "Ly": Ly, "dp": dp, "vmax": vmax, "scene": sc, "g": g, "H": H, "tend": tend, "a": a,
             "c0": cfg["c0"], "rho_rms_dev": meta_s.get("rho_rms_dev"), "effective": cfg,
             "time_unit": "s" if len(all_t) >= n else "frame"}
    if sc == "ship":
        hints["hull"] = [np.fromfile(Path(tmp) / f"hull_{i:05d}.bin", dtype=np.float32).reshape(-1, 2)
                         for i in idx]
    return Result("particles", raw, f"{p.get('scene', 'Dam break')}  ({len(raw[-1])} particles)",
                  hints=hints, times=times)


def _solve_spectral(p, pr, tmp):
    from .spectral import Spectral2D, double_shear_layer, random_field
    cfg = _spectral_config(p); n, nu, L = cfg["n"], cfg["nu"], cfg["L"]
    sim = Spectral2D(n=n, L=L, nu=nu)
    if p.get("init") == "Random turbulence":
        wh = random_field(n, seed=int(p.get("seed", 1))); label = "decaying turbulence"
    elif p.get("init") == "Taylor–Green vortex":
        from .spectral import taylor_green
        wh = taylor_green(n); label = "Taylor–Green vortex"
    else:
        wh = double_shear_layer(n, amp=float(p["perturbation"]), delta=float(p.get("thickness", 1 / 30)))
        label = "Kelvin–Helmholtz"
    # The simulated interval belongs to the EXPERIMENT, not the resolution: fix T_end from
    # the duration at the reference grid (n0=256) and take however many CFL-limited steps
    # that needs here. (Before, the step count was fixed while dt ~ 1/n, so "Ultra"
    # silently simulated about half the time of "Medium".)
    T_end, dt, steps = cfg["T_end"], cfg["dt"], cfg["steps"]
    pr(f"spectral {n}×{n}, ν={nu:.1e}, T={T_end:.2f}, {steps} steps…")
    vel = []; times = []; _pp = max(1, steps // 50); every = max(1, steps // 90)
    for st in range(steps + 1):
        if st % every == 0 or st == steps:
            u, v = sim.velocity(wh)
            vel.append((u.T.copy(), v.T.copy()))      # solver works in [x, y]; public arrays are [y, x]
            times.append(st * dt)
        if st % _pp == 0:
            pr(f"simulating… {int(100 * st / steps)}%")
        if st < steps:
            wh = sim.step(wh, dt)
            if st % _pp == 0 and not np.isfinite(wh).all():
                raise ValueError(f"spectral field became non-finite at step {st} (dt={dt:.4g}, ν={nu:g}); "
                                 "reduce the viscosity or the perturbation")
    r = Result("spectral", vel, f"{label}  {n}×{n}", times=times,
               hints={"dx": L / n, "L": L, "dt": dt, "T_end": T_end, "nu": nu, "time_unit": "nondimensional (L = 2π)",
                      "init": "Taylor–Green" if label == "Taylor–Green vortex" else label})
    return r


def _solve_mixing(p, pr, tmp):
    from .spectral import Spectral2D, random_field, advect_sl
    cfg = _spectral_config(p, mixing=True); n, nu, T_end, dt, steps = cfg["n"], cfg["nu"], cfg["T_end"], cfg["dt"], cfg["steps"]
    sim = Spectral2D(n=n, nu=nu); wh = random_field(n, seed=int(p.get("seed", 3)))
    stir = float(p.get("stir", 1.0))                       # 0 = diffusion only, 1 = full stirring
    L = 2 * np.pi
    # dye: alternating horizontal bands (so stirring shows the folding/filamentation)
    yy = np.linspace(0, L, n, endpoint=False)[None, :] * np.ones((n, 1))
    c = 0.5 * (1 + np.sign(np.sin(float(p.get("bands", 6)) * yy)))
    kap = float(p.get("diffusion", 1e-4))
    pr(f"chaotic mixing {n}×{n}, {steps} steps…")
    raw = []; times = []; _pp = max(1, steps // 50)
    for st in range(steps + 1):
        u, v = sim.velocity(wh)
        if st % max(1, steps // 100) == 0:
            raw.append(c.T.copy()); times.append(st * dt)     # solver is [x,y]; public arrays are [y,x]
        if st % _pp == 0:
            pr(f"simulating… {int(100 * st / steps)}%")
        if stir > 0:
            c = advect_sl(c, stir * u, stir * v, dt, L)
        if kap > 0:                                   # gentle scalar diffusion (spectral)
            c = np.real(np.fft.ifft2(np.exp(-kap * sim.k2 * dt) * np.fft.fft2(c)))
        wh = sim.step(wh, dt)
        if st % _pp == 0 and not (np.isfinite(wh).all() and np.isfinite(c).all()):
            raise ValueError(f"mixing field became non-finite at step {st}")
    return Result("field", raw, f"chaotic mixing  {n}×{n}", times=times,
                  hints={"label": "dye", "dx": L / n, "dt": dt, "T_end": T_end, "nu": nu, "kappa": kap,
                         "stir": stir, "time_unit": "nondimensional (L = 2π)"})


def _solve_reaction(p, pr, tmp):
    from .reaction import gray_scott, PRESETS
    s = _res(p); n = int(220 * s)
    pat = p.get("pattern", "Spots")
    if pat == "Custom":
        F, k = float(p.get("F", 0.035)), float(p.get("k", 0.065))
    else:
        F, k = PRESETS.get(pat, (0.035, 0.065))
    Du, Dv = float(p.get("Du", 0.16)), float(p.get("Dv", 0.08))
    steps = int(9000 * _durv(p))
    pr(f"Gray–Scott {n}×{n}, {pat} (F={F:.4f}, k={k:.4f}), {steps} steps…")
    frames = gray_scott(n=n, F=F, k=k, Du=Du, Dv=Dv, steps=steps, nframes=110, seed=int(p.get("seed", 1)),
                        progress=lambda f: pr(f"simulating… {int(100 * f)}%"))
    every = max(1, steps // 110)
    times = [float(i * every) for i in range(len(frames))]
    return Result("field", frames, f"{pat}  {n}×{n}", times=times,
                  hints={"label": "V concentration", "F": F, "k": k, "Du": Du, "Dv": Dv,
                         "time_unit": "steps (dt = 1)", "steps": steps})


def _solve_quantum(p, pr, tmp):
    from .quantum import simulate
    s = _res(p); n = int(220 * s); steps = int(360 * _durv(p))
    scene = {"Free spreading": "free", "Tunnelling barrier": "barrier",
             "Double slit": "slit", "Harmonic well": "harmonic"}.get(p.get("scene", "Tunnelling barrier"), "barrier")
    pr(f"Schrödinger {n}×{n} ({scene}), {steps} steps…")
    prob, phase, V, norm = simulate(n=n, scene=scene, steps=steps, nframes=110,
                                    k0=float(p.get("momentum", 360)), width=float(p.get("width", 0.06)),
                                    v0=float(p.get("barrier", 320)),
                                    progress=lambda f: pr(f"simulating… {int(100 * f)}%"))
    if scene == "harmonic":          # closed system → unitarity check
        info = f"harmonic well  {n}×{n} · norm conserved to {max(abs(x - 1) for x in norm):.0e}"
    else:                            # open: the absorbing border removes escaping probability
        info = f"{scene}  {n}×{n} · absorbing boundary"
    return Result("quantum", prob, info, hints={"phase": phase, "norm": norm, "scene": scene})


EXHIBITS = {
    "Wind Tunnel": {
        "params": [{"name": "obstacle", "label": "Obstacle", "type": "choice", "group": "Geometry",
                    "choices": ["Cylinder", "Square", "Diamond", "Airfoil",
                                "F1 car", "Cyclist", "Peloton (drafting)", "Your text"],
                    "default": "Cylinder",
                    "help": "What to drop into the stream — a shape, a vehicle, or your own text."},
                   _when({"name": "text", "label": "Your text", "type": "str", "default": "Funoos", "max_len": 24,
                          "group": "Geometry", "help": "The word to drop into the stream. Short words read best."},
                         "obstacle", ["Your text"]),
                   _when(_f("size", "Obstacle size", 0.13, 0.05, 0.30, "Geometry",
                            "Obstacle size (cylinder diameter, square side, airfoil chord/2.6) as a fraction "
                            "of the channel height. Bigger → larger, slower-shedding wake.",
                            units="× height", hard_min=0.02, hard_max=0.6,
                            fixed="Re is held: ν is recomputed from the new D"),
                         "obstacle", ["Cylinder", "Square", "Diamond", "Airfoil"]),
                   _when(_f("angle", "Airfoil angle of attack", 12, -25, 25, "Geometry",
                            "Angle of attack in degrees; positive = leading edge up (lift upward). "
                            "Negative angles mirror the flow and give downward lift.", units="°",
                            hard_min=-45, hard_max=45), "obstacle", ["Airfoil"]),
                   _f("reynolds", "Reynolds number", 160, 30, 1200, "Physics", _H["Re"], hard_min=5, hard_max=5000,
                      fixed="U and D stay; ν = U·D/Re changes"),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"], units="lattice",
                      hard_min=0.005, hard_max=0.25, fixed="Re stays; ν changes with U"),
                   _f("xpos", "Obstacle position", 0.25, 0.15, 0.5, "Geometry",
                      "Streamwise position of the obstacle centre as a fraction of the tunnel length "
                      "(vehicles and text use their own placement).", units="× length", hard_min=0.05,
                      hard_max=0.8, advanced=True),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_windtunnel(p, pr, t)},
    "Rising Smoke": {
        "params": [_f("buoyancy", "Buoyancy coefficient", 2.5e-3, 5e-4, 6e-3, "Physics", _H["buoy"],
                      units="grid units", hard_min=0, hard_max=0.05),
                   _f("confinement", "Vorticity confinement", 8, 0, 20, "Physics", _H["conf"], hard_min=0, hard_max=60),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"], units="grid units", hard_min=0, hard_max=0.05),
                   _f("flicker", "Source flicker", 0.0, 0.0, 1.0, "Physics",
                      "Wobble & pulse the source (a prescribed modulation of the inflow, not a physical "
                      "instability). 0 = a steady column; 1 = a lively, flame-like pulse.", hard_min=0, hard_max=1),
                   _f("source", "Source width", 1.0, 0.3, 3.0, "Geometry",
                      "Width of the hot source at the floor.", units="×", hard_min=0.1, hard_max=6),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("smoke", p, pr, t)},
    "Candle Flame": {
        "params": [_f("buoyancy", "Heat-release buoyancy", 0.020, 0.008, 0.03, "Physics",
                      "How strongly the temperature proxy T(Z) lifts the gas. Stronger buoyancy draws "
                      "the fuel up faster, keeping the flame slender and steady.", units="grid units",
                      hard_min=0, hard_max=0.1),
                   _f("zst", "Stoichiometric mixture  Z_st", 0.18, 0.08, 0.30, "Physics",
                      "The fuel/air ratio at which the flame sheet sits. The luminous sheet is the "
                      "Z = Z_st surface; a larger value pulls it tighter to the fuel core.", hard_min=0.02, hard_max=0.9),
                   _f("source", "Wick width", 0.45, 0.3, 1.5, "Geometry",
                      "Width of the fuel vapour leaving the wick. A thin wick gives a slender flame.",
                      units="×", hard_min=0.1, hard_max=4),
                   _f("confinement", "Vorticity confinement", 4, 0, 20, "Physics",
                      "Sharpens the small eddies that make the flame tip lick and wander (a modelling knob).",
                      hard_min=0, hard_max=60),
                   _f("viscosity", "Viscosity", 2.5e-4, 5e-5, 6e-4, "Physics", _H["visc"], units="grid units",
                      hard_min=0, hard_max=0.05),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("flame", p, pr, t)},
    "Mushroom Clouds": {
        "params": [_f("atwood", "Atwood number", 0.7, 0.2, 1.0, "Physics",
                      "A = (ρ_heavy − ρ_light)/(ρ_heavy + ρ_light), the density contrast across the "
                      "interface. Higher A → faster, narrower spikes. (Boussinesq-like model: density "
                      "only enters the buoyancy force; see the scene notes.)", hard_min=0.01, hard_max=1.0),
                   _f("gravity", "Gravity", 1.2e-3, 4e-4, 3e-3, "Physics", _H["grav"], units="grid units",
                      hard_min=0, hard_max=0.05),
                   _f("viscosity", "Viscosity", 1.5e-4, 3e-5, 5e-4, "Physics", _H["visc"], units="grid units",
                      hard_min=0, hard_max=0.05),
                   _f("perturbation", "Interface ripple", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the initial interface ripple that seeds the fingers.",
                      units="×", hard_min=0, hard_max=10),
                   _i("modes", "Single-mode wavenumber", 0, 0, 8, "Physics",
                      "0 = the multi-mode ripple (modes 3 + 7). A value n ≥ 1 seeds a single cosine mode with n "
                      "wavelengths across the box and a small amplitude, for measuring the early growth of one mode.",
                      hard_min=0, hard_max=32, advanced=True),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rt", p, pr, t)},
    "Rayleigh-Benard": {
        "params": [_f("buoyancy", "Buoyancy coefficient  β·ΔT", 6e-3, 0.0, 1.2e-2, "Physics",
                      "Buoyant acceleration per unit temperature difference. With the viscosity and "
                      "thermal diffusivity it sets the Rayleigh number Ra = β·ΔT·H³/(ν κ) shown in the "
                      "derived quantities — this control is NOT itself a Rayleigh number. 0 = pure conduction.",
                      units="grid units", hard_min=0, hard_max=0.1),
                   _f("viscosity", "Viscosity ν", 6e-4, 2e-4, 1.5e-3, "Physics",
                      "Damps the motion. Lower viscosity → a higher Rayleigh number → tighter, more chaotic cells.",
                      units="grid units", hard_min=1e-6, hard_max=0.05),
                   _f("kappa", "Thermal diffusivity κ", 0.02, 0.005, 0.1, "Physics",
                      "Conduction of heat. Together with ν it sets the Prandtl number ν/κ and the Rayleigh "
                      "number. (Explicit diffusion step: κ·dt must stay ≤ 0.25.)", units="grid units",
                      hard_min=0, hard_max=0.25, advanced=True),
                   _f("perturbation", "Seed ripple", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the tiny temperature perturbation that breaks the symmetry and "
                      "selects the cell wavelength.", units="×", hard_min=0, hard_max=10),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rb", p, pr, t)},
    "Chimney Plume": {
        "params": [_f("buoyancy", "Buoyancy coefficient", 5e-3, 2e-3, 1e-2, "Physics", _H["buoy"],
                      units="grid units", hard_min=0, hard_max=0.05),
                   _f("wind", "Crosswind speed", 0.30, 0.0, 0.55, "Physics",
                      "Speed of the horizontal wind across the stack. Stronger wind bends the plume over "
                      "closer to the ground (a smaller plume rise). 0 = calm air.", units="grid units/step",
                      hard_min=0, hard_max=0.8),
                   _f("confinement", "Vorticity confinement", 6, 0, 20, "Physics", _H["conf"], hard_min=0, hard_max=60),
                   _f("source", "Stack width", 0.6, 0.3, 3.0, "Geometry",
                      "Width of the chimney source at the floor.", units="×", hard_min=0.1, hard_max=6),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"], units="grid units", hard_min=0, hard_max=0.05),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("wind", p, pr, t)},
    "Detonation": {
        "params": [{"name": "scene", "label": "Scene", "type": "choice", "group": "Geometry",
                    "choices": ["Open air", "Shock hits a city"], "default": "Open air",
                    "help": "Open air: a free blast wave expanding into still gas. Shock hits a city: a "
                    "ground burst whose blast diffracts around and reflects off two solid towers."},
                   _f("pressure", "Charge pressure ratio  p₀ / p_ambient", 100.0, 20.0, 400.0, "Physics",
                      "Pressure inside the charge relative to the ambient pressure (0.1 in code units). "
                      "Higher → a stronger, faster shock. The solver receives p₀ = ratio × 0.1.",
                      hard_min=1.01, hard_max=5000),
                   _f("charge", "Charge size", 0.06, 0.02, 0.18, "Geometry",
                      "Radius of the high-pressure charge as a fraction of the domain width.",
                      units="× width", hard_min=0.005, hard_max=0.4),
                   _when({"name": "structure", "label": "Structure model", "type": "choice", "group": "Physics",
                          "choices": ["Rigid walls", "Erodes (experimental)"], "default": "Rigid walls",
                          "help": "Rigid walls: the towers are fixed reflecting obstacles. Erodes: an experimental "
                          "rule removes a block when the overpressure on an exposed face exceeds its strength "
                          "(not a structural-mechanics model)."}, "scene", ["Shock hits a city"]),
                   _when(_f("strength", "Structure strength", 1.0, 0.2, 3.0, "Physics",
                            "Overpressure each block can take before it fails (erosion model only). Weak "
                            "structures are scoured away windward-first.",
                            hard_min=0.01, hard_max=1000),
                         "structure", ["Erodes (experimental)"]),
                   _i("debris", "Debris particles", 200, 0, 800, "Render",
                      "Glowing debris swept outward by the blast (visual only; not part of the solution).",
                      hard_min=0, hard_max=5000),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("blast", p, pr, t)},
    "Shock Tube": {
        "params": [P_RES("Cells along the tube (the tube is one-dimensional; the strip is for display). "
                         "Higher resolution sharpens the shock and contact discontinuity."),
                   P_DUR("Fraction of the reference time 0.2 (tube length 1); at 1.0 the waves have not yet reached the ends.")],
        "solve": lambda p, pr, t: _solve_euler("sod", p, pr, t)},
    "Shockwave Strike": {
        "params": [{"name": "target", "label": "Target", "type": "choice", "group": "Geometry",
                    "choices": ["Single bubble", "Two bubbles"], "default": "Single bubble",
                    "help": "One gas bubble, or two stacked bubbles whose roll-ups interact."},
                   _f("mach", "Shock Mach number", 1.5, 1.1, 3.0, "Physics",
                      "Strength of the incoming shock, M_s = (shock speed)/(sound speed). The post-shock "
                      "state follows the exact Rankine–Hugoniot relations (see derived quantities).",
                      hard_min=1.01, hard_max=10),
                   _f("densratio", "Density ratio ρ_bubble/ρ_air", 0.18, 0.05, 4.0, "Physics",
                      "Bubble density ÷ ambient density. <1 = a light bubble (rolls up fast); >1 = a heavy "
                      "bubble (the shock slows and focuses inside it).", hard_min=0.01, hard_max=50),
                   _f("bubble", "Bubble size", 0.18, 0.08, 0.32, "Geometry",
                      "Bubble radius as a fraction of the domain height.", units="× height", hard_min=0.02, hard_max=0.45),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("bubble", p, pr, t)},
    "The Big Splash": {
        "params": [{"name": "scene", "label": "Scene", "type": "choice", "group": "Geometry",
                    "choices": ["Dam break", "Drop & splash", "Sloshing tank",
                                "Pour into a glass", "Wave tank", "Ship on waves", "Still water (hydrostatic)"],
                    "default": "Dam break",
                    "help": "Which free-surface scenario to run. Each scene exposes its own controls below. "
                    "Still water is the hydrostatic baseline: nothing should move."},
                   _when(_f("width", "Dam width", 1.0, 0.4, 2.0, "Geometry",
                            "Width of the held-back water column (tank 5 × 3.2 m).", units="m",
                            hard_min=0.1, hard_max=4.9), "scene", ["Dam break"]),
                   _when(_f("height", "Dam height", 2.0, 0.6, 3.0, "Geometry",
                            "Height of the column — more head → a faster, taller surge.", units="m",
                            hard_min=0.1, hard_max=3.1), "scene", ["Dam break"]),
                   _when(_f("dropsize", "Blob diameter", 0.4, 0.2, 0.8, "Geometry",
                            "Diameter of the falling water blob (a parcel of water, not a capillary "
                            "droplet — there is no surface tension in this model).", units="m",
                            hard_min=0.06, hard_max=1.5), "scene", ["Drop & splash"]),
                   _when(_f("dropheight", "Release height", 0.70, 0.45, 0.92, "Geometry",
                            "How high the blob starts, as a fraction of tank height (sets the impact speed "
                            "√(2 g h)).", units="× height", hard_min=0.35, hard_max=0.95), "scene", ["Drop & splash"]),
                   _when(_f("sloshA", "Slosh strength", 0.7, 0.1, 1.5, "Physics",
                            "Amplitude of the oscillating sideways gravity, as a multiple of g.", units="× g",
                            hard_min=0, hard_max=5), "scene", ["Sloshing tank"]),
                   _when(_f("sloshT", "Slosh period", 1.1, 0.5, 3.0, "Physics",
                            "Period of the side-to-side forcing. Near the tank's natural period the wave "
                            "resonates and breaks.", units="s", hard_min=0.1, hard_max=20), "scene", ["Sloshing tank"]),
                   _when(_f("spout", "Spout width", 0.045, 0.02, 0.12, "Geometry",
                            "Half-width of the pour stream as a fraction of the glass width. Values below "
                            "3 particle spacings are raised to that minimum (shown in derived quantities).",
                            units="× width", hard_min=0.005, hard_max=0.4), "scene", ["Pour into a glass"]),
                   _when(_f("pourv", "Pour speed", 1.4, 0.4, 3.0, "Physics",
                            "Speed the water leaves the spout. Faster → more splashing on impact.",
                            units="m/s", hard_min=0.05, hard_max=10), "scene", ["Pour into a glass"]),
                   _when(_f("waveA", "Wavemaker stroke", 0.4, 0.0, 0.9, "Physics",
                            "Stroke of the wavemaker paddle (the wall's travel), which sets the wave amplitude "
                            "indirectly — it is not the wave height itself. 0 = still paddle (free decay / "
                            "equilibrium test for the ship).", units="m",
                            hard_min=0.0, hard_max=2.0), "scene", ["Wave tank", "Ship on waves"]),
                   _when(_f("waveT", "Wave period", 0.9, 0.4, 2.0, "Physics",
                            "Period of the wavemaker — sets the wavelength of the train.", units="s",
                            hard_min=0.1, hard_max=10), "scene", ["Wave tank", "Ship on waves"]),
                   _when(_f("shipsz", "Ship size", 1.0, 0.5, 1.8, "Geometry",
                            "Scale of the floating hull. Bigger ships sit deeper and roll slower.", units="×",
                            hard_min=0.2, hard_max=3), "scene", ["Ship on waves"]),
                   _when(_i("particles", "Particles (≈)", 3000, 600, 12000, "Geometry",
                            "Approximate number of SPH particles: sets the particle spacing dp (see derived "
                            "quantities). More → finer splash, slower. The pour scene emits particles "
                            "continuously and ignores this.", hard_min=200, hard_max=40000),
                         "scene", ["Dam break", "Drop & splash", "Sloshing tank", "Wave tank", "Ship on waves", "Still water (hydrostatic)"]),
                   _f("gravity", "Gravity", 9.81, 1.0, 25.0, "Physics", "Gravitational acceleration.",
                      units="m/s²", hard_min=0.1, hard_max=100),
                   P_DUR()],
        "solve": lambda p, pr, t: _solve_dam(p, pr, t)},
    "Cloud Billows": {
        "params": [{"name": "init", "label": "Initial field", "type": "choice", "group": "Geometry",
                    "choices": ["Shear layers", "Random turbulence", "Taylor–Green vortex"], "default": "Shear layers",
                    "help": "Shear layers roll into Kelvin–Helmholtz billows; random turbulence decays as "
                    "vortices merge (the 2-D inverse cascade); the Taylor–Green vortex is an exact decaying "
                    "solution (energy ∝ exp(−4νt)) used to check the solver."},
                   _f("viscosity", "Viscosity ν", 8e-5, 1e-5, 4e-4, "Physics", _H["visc"], hard_min=0, hard_max=0.01),
                   _when(_f("perturbation", "Shear perturbation", 0.05, 0.005, 0.2, "Physics",
                            "Amplitude of the initial transverse velocity kick that seeds the billows.",
                            hard_min=0, hard_max=1), "init", ["Shear layers"]),
                   _when(_f("thickness", "Shear-layer thickness", 1 / 30, 0.01, 0.1, "Physics",
                            "Thickness of each tanh shear layer as a fraction of the box size L.",
                            units="× L", hard_min=0.003, hard_max=0.25, advanced=True), "init", ["Shear layers"]),
                   _when(_i("seed", "Random seed", 1, 0, 9999, "Physics",
                            "Seed of the random initial vorticity (same seed → same experiment).",
                            hard_min=0, hard_max=2 ** 31 - 1, advanced=True), "init", ["Random turbulence"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_spectral(p, pr, t)},
    "Tracer in Rock": {
        "params": [_f("porosity", "Porosity φ", 0.60, 0.40, 0.85, "Geometry",
                      "Fraction of the sample that is pore space. The same rock as the porous-flow "
                      "experiment: with the same porosity, grain size and seed you get the same sample.",
                      hard_min=0.25, hard_max=0.95),
                   _f("grain", "Grain size", 0.035, 0.02, 0.07, "Geometry",
                      "Typical grain radius as a fraction of the sample height. It also sets the length "
                      "in the Péclet number.", units="× height", hard_min=0.01, hard_max=0.15),
                   _i("seed", "Sample seed", 1, 0, 9999, "Geometry",
                      "Which random grain arrangement to pack. Same seed, same rock.", hard_min=0, hard_max=99999),
                   {"name": "direction", "label": "Driving direction", "type": "choice", "choices": ["x", "y"],
                    "default": "x", "group": "Physics", "help": "Which way the flow (and the tracer) is driven."},
                   _f("strength", "Driving strength", 1.0, 0.25, 4.0, "Physics",
                      "Body force driving the flow, as a multiple of the default. In the Darcy regime it "
                      "changes the speed but not the permeability; with the Péclet number held, it does not "
                      "change the spreading either.", hard_min=0.05, hard_max=20,
                      fixed="Pe is held: the molecular diffusivity is rescaled with the pore speed"),
                   _f("peclet", "Péclet number", 20.0, 0.1, 400.0, "Physics",
                      "How strongly the tracer is carried compared with how fast it spreads: "
                      "Pe = u·d/D_m with u the pore speed and d the grain size. Below 1 diffusion dominates "
                      "and the plume stays symmetric; above about 10 fast and slow channels stretch it and "
                      "the breakthrough curve grows a long tail.", hard_min=0.01, hard_max=5000,
                      fixed="the molecular diffusivity follows from Pe and the measured pore speed"),
                   {"name": "injection", "label": "Injection", "type": "choice",
                    "choices": ["Continuous supply", "Pulse"], "default": "Continuous supply", "group": "Physics",
                    "help": "A continuous supply holds the inlet at full concentration and sends a front "
                            "through the sample; the outlet curve climbs towards 1. A pulse releases one slug "
                            "instead, which passes and leaves, giving a curve that rises, peaks and decays."},
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_tracer(p, pr, t)},
    "Porous Flow": {
        "params": [_f("porosity", "Porosity  φ", 0.60, 0.40, 0.85, "Geometry",
                      "Fraction of the sample that is open pore space. Lower porosity (denser grain "
                      "packing) → far lower permeability.", units="void fraction", hard_min=0.2, hard_max=0.95),
                   _f("grain", "Grain size", 0.035, 0.02, 0.07, "Geometry",
                      "Radius of the packed grains as a fraction of the sample height.", units="× height",
                      hard_min=0.008, hard_max=0.15),
                   _i("seed", "Random seed", 1, 0, 9999, "Geometry",
                      "Seed of the random grain arrangement: change it to compare samples with the same "
                      "porosity but different connectivity.", hard_min=0, hard_max=2 ** 31 - 1, advanced=True),
                   {"name": "direction", "label": "Driving direction", "type": "choice", "group": "Physics",
                    "choices": ["x", "y"], "default": "x",
                    "help": "Direction of the body force. Run both to measure the directional permeability "
                    "k_x and k_y of the same sample (anisotropy)."},
                   _f("strength", "Driving strength", 1.0, 0.25, 4.0, "Physics",
                      "Multiplier on the body force (1 = 1.2e-5 lattice units). In the Darcy regime k must not "
                      "depend on it — sweep it to check linearity.", units="×", hard_min=0.01, hard_max=50, advanced=True),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_porous(p, pr, t)},
    "Turing Patterns": {
        "params": [{"name": "pattern", "label": "Pattern", "type": "choice", "group": "Geometry",
                    "choices": ["Spots", "Stripes", "Maze", "Mitosis", "Coral", "Waves", "Custom"],
                    "default": "Spots",
                    "help": "Each pattern is a (feed F, removal k) regime of the Gray–Scott model from "
                    "Pearson's classification; Custom lets you set F and k yourself."},
                   _when(_f("F", "Feed rate F", 0.035, 0.01, 0.08, "Physics",
                            "Rate at which U is fed in (and V removed with k).", hard_min=0, hard_max=0.3),
                         "pattern", ["Custom"]),
                   _when(_f("k", "Removal rate k", 0.065, 0.04, 0.075, "Physics",
                            "Rate at which V is removed.", hard_min=0, hard_max=0.3), "pattern", ["Custom"]),
                   _f("Du", "Diffusivity of U", 0.16, 0.05, 0.25, "Physics",
                      "Diffusion coefficient of U (explicit scheme: keep Du ≤ 0.25 for stability at dt = 1).",
                      hard_min=0, hard_max=0.25, advanced=True),
                   _f("Dv", "Diffusivity of V", 0.08, 0.02, 0.2, "Physics",
                      "Diffusion coefficient of V. Patterns need Dv < Du (Turing's condition).",
                      hard_min=0, hard_max=0.25, advanced=True),
                   _i("seed", "Random seed", 1, 0, 9999, "Geometry",
                      "Seed of the initial noisy blobs (same seed → same pattern).", hard_min=0,
                      hard_max=2 ** 31 - 1, advanced=True),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_reaction(p, pr, t)},
    "Ink in Motion": {
        "params": [_i("bands", "Dye bands", 6, 2, 14, "Geometry",
                      "How many horizontal stripes of dye to start with.", hard_min=1, hard_max=64),
                   _f("diffusion", "Dye diffusivity κ", 1e-4, 0.0, 1e-3, "Physics",
                      "Molecular diffusion of the dye — higher blurs the fine filaments sooner. 0 = pure "
                      "stirring (only numerical diffusion remains).", hard_min=0, hard_max=0.05),
                   _f("stir", "Stirring strength", 1.0, 0.0, 1.0, "Physics",
                      "Multiplies the stirring velocity: 1 = the full turbulent flow, 0 = diffusion only "
                      "(compare how much mixing comes from stirring versus diffusion).",
                      hard_min=0, hard_max=3, advanced=True),
                   _i("seed", "Random seed", 3, 0, 9999, "Physics",
                      "Seed of the random stirring flow.", hard_min=0, hard_max=2 ** 31 - 1, advanced=True),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_mixing(p, pr, t)},
}

_LBM_EQ = r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q(\mathbf{x},t)-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$"
_EULER_EQ = r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\quad \mathbf{U}=[\rho,\ \rho u,\ \rho v,\ E]$"

META = {
    "Wind Tunnel": {"method": "Flow past an obstacle · Lattice-Boltzmann (D2Q9)",
        "blurb": "Drop something into a steady stream and watch the wake. Past a critical "
                 "Reynolds number the flow can no longer stay attached: it separates, sheds "
                 "vortices alternately from each side, and trails the famous von Kármán "
                 "vortex street — the same wake that sings in wires and shakes chimneys, "
                 "bridge decks and offshore risers. Choose a cylinder, a square, a diamond, "
                 "an angled airfoil, or even your own name, and see how the shape rewrites "
                 "the wake.",
        "eq": _LBM_EQ,
        "numerics": "Solved with a D2Q9 lattice-Boltzmann method: nine discrete velocities "
                    "per cell, a single-relaxation-time (BGK) collision toward the local "
                    "equilibrium, and a streaming step that shifts populations to neighbours. "
                    "The obstacle — any shape or text — is simply a set of cells flagged solid "
                    "and handled by half-way bounce-back (a no-slip wall); obstacles are represented on "
                    "the regular lattice, so a body-fitted mesh is unnecessary. Velocity inlet, zero-gradient "
                    "outflow, periodic top/bottom; the "
                    "relaxation time τ sets the viscosity via ν = (τ − ½)/3, hence the Reynolds number.",
        "validation": "Numerical check: the measured shedding frequency of a cylinder, as a Strouhal number "
                       "St = fD/U, is compared with the reference range 0.18–0.21 (Re 100–300); this confined, "
                       "periodic tunnel is expected to sit slightly above an unconfined cylinder.",
        "demo": "results/flow_around_flowzoo.gif"},
    "Rising Smoke": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "A continuous source of hot, dyed fluid is injected at the floor. Because it "
                 "is lighter than its surroundings, buoyancy drives it upward; as it rises it "
                 "shears against the still air, rolls up into vortices, and breaks into the "
                 "turbulent, billowing column we recognise as smoke. This is the canonical "
                 "buoyancy-driven incompressible flow, and the same machinery underlies "
                 "visual-effects smoke, plume dispersion and indoor-air modelling.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f}_b,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "A projection ('stable fluids') method: unconditionally-stable "
                    "semi-Lagrangian advection, a red-black Gauss–Seidel SOR solve of the "
                    "pressure-Poisson equation to enforce ∇·u = 0, a Boussinesq buoyancy "
                    "force proportional to the transported temperature/dye, and vorticity "
                    "confinement that re-injects the fine swirls numerical diffusion erodes.",
        "validation": "The velocity field is kept divergence-free to the projection "
                       "tolerance each step; buoyant transport stays stable and the plume "
                       "develops the expected shear roll-up.",
        "demo": "results/smoke_plume.gif"},
    "Candle Flame": {"method": "Simplified flame model · Navier–Stokes + mixture variable",
        "blurb": "A candle is a non-premixed (diffusion) flame: fuel vapour rises from the wick, air "
                 "is drawn in from the sides, and burning is confined to the surface where they meet in "
                 "stoichiometric proportion. This scene uses a simplified flame model: an advected mixture "
                 "variable Z with a prescribed source velocity at the wick, a temperature proxy T(Z) that "
                 "peaks on the stoichiometric surface, buoyancy proportional to that proxy, lateral damping "
                 "and scalar decay. No chemistry or heat release is computed.",
        "eq": r"$\partial_t Z+\mathbf{u}\!\cdot\!\nabla Z=\mathcal{D}\nabla^2 Z,\quad T(Z)=T_{\rm ad}\,\min\!\left(\dfrac{Z}{Z_{st}},\ \dfrac{1-Z}{1-Z_{st}}\right),\quad \mathbf{f}_b=\beta\,T(Z)\,\hat{\mathbf{y}}$",
        "numerics": "The incompressible projection solver carries a mixture variable Z (Z = 1 in the "
                    "fuel leaving the wick, Z = 0 in the surrounding air) with a prescribed inflow velocity "
                    "at the wick, lateral damping of the flow and a decay of Z away from the source. In the "
                    "Burke–Schumann picture the flame sheet sits on Z = Z_st, where the temperature proxy "
                    "T(Z) (a tent function of Z) peaks; that proxy drives the Boussinesq buoyancy and is the "
                    "field rendered.",
        "validation": "Qualitative demonstration: the shape anchors on the wick and the tip flickers "
                       "periodically; the flicker frequency is reported in the plots but not compared with "
                       "measurements."},
    "Mushroom Clouds": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "Place a heavy fluid on top of a lighter one in a gravitational field and "
                 "the arrangement is unstable: the tiniest ripple on the interface grows, the "
                 "heavy fluid sinks in falling spikes while the light fluid rises in bubbles, "
                 "and each finger curls into the classic mushroom cap. The Rayleigh–Taylor "
                 "instability governs phenomena from supernova remnants and inertial-"
                 "confinement fusion to salt domes and atmospheric mixing.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}-g\,\rho\,\hat{\mathbf{y}},\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The same constant-density projection solver with an advected scalar ρ that enters "
                    "only the gravitational body force (a Boussinesq-like approximation: inertia does not "
                    "change with density). The interface is seeded with a multi-mode ripple, or a single "
                    "mode of chosen wavenumber.",
        "validation": "Qualitative demonstration of the spike-and-bubble roll-up; the mixing-width diagnostic "
                       "is consistent across resolutions, but large-Atwood growth rates are not claimed because "
                       "the model is not a variable-density formulation.",
        "demo": "results/rayleigh_taylor.gif"},
    "Rayleigh-Benard": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "Heat a shallow layer of fluid from below and cool it from above and, once the "
                 "temperature difference is large enough, pure conduction can no longer carry the "
                 "heat: the layer overturns. Warm fluid rises in plumes, cool fluid sinks, and the "
                 "motion organises into a regular train of counter-rotating convection cells — "
                 "Rayleigh–Bénard convection. It is the textbook example of pattern formation from "
                 "instability, and the same engine of buoyant overturning drives the atmosphere, "
                 "the oceans, boiling pots and the Earth's mantle.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\alpha g\,T\,\hat{\mathbf{y}},\quad \partial_t T+\mathbf{u}\!\cdot\!\nabla T=\kappa\nabla^2T,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The incompressible projection solver coupled to a transported temperature "
                    "field under the Boussinesq approximation (buoyancy ∝ T). The bottom and top "
                    "rows are held at fixed hot and cold temperatures (Dirichlet plates), the side "
                    "walls are insulating, and a tiny initial perturbation seeds the cells. The "
                    "ratio of buoyant forcing to viscous and diffusive damping is the Rayleigh number.",
        "validation": "Numerical check: with buoyancy off the explicit diffusion step preserves the linear "
                       "conduction profile (tests/) and the Nusselt number is 1. The Rayleigh number "
                       "Ra = β·ΔT·H³/(ν κ) is computed from the controls; the plates are free-slip and conducting "
                       "(onset Ra ≈ 657.5 in linear theory; 1708 is the no-slip value), and at this grid Ra lies far "
                       "above both, so the onset regime itself is not reachable."},
    "Chimney Plume": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "A buoyant plume leaves a stack into a steady crosswind. Near the source buoyancy "
                 "lifts it almost vertically, but the horizontal wind keeps pushing, so the plume "
                 "bends over into the familiar slanted chimney trail before levelling off downwind. "
                 "The balance between buoyancy and wind sets the 'plume rise' — the same physics "
                 "engineers use to size smokestacks and predict how pollutants disperse.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f}_b,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The projection solver with a hot, dyed source at the floor and a velocity "
                    "inlet on the left that drives a uniform crosswind (zero-gradient outflow on the "
                    "right, open top). Boussinesq buoyancy lifts the dyed fluid while the mean wind "
                    "advects it downstream, so the steady plume trajectory emerges from the force balance.",
        "validation": "The plume rises then bends over, and its rise height falls as the crosswind "
                       "strengthens — the expected buoyancy-versus-momentum trade-off of plume-rise theory."},
    "Detonation": {"method": "Blast wave (pressure release) · Compressible Euler · finite-volume HLLC",
        "blurb": "A small region of high-pressure gas is released into ambient gas — a pressure-release "
                 "model, not a detonation (no reaction or energy release is computed). It bursts outward as "
                 "a near-circular shock wave, a thin front across which density, pressure and velocity jump, "
                 "trailed by an expansion that leaves a low-density cavity. Debris particles are a visual "
                 "overlay.",
        "eq": _EULER_EQ,
        "numerics": "A finite-volume solver for the compressible Euler equations: "
                    "piecewise-linear MUSCL reconstruction with a minmod slope limiter, an "
                    "HLLC approximate Riemann solver at each cell face, and a two-stage "
                    "strong-stability-preserving Runge–Kutta time step under a CFL condition "
                    "(γ = 1.4). Schlieren imaging shows |∇ρ|, lighting up the shock fronts. In "
                    "the city scene the towers are cells held at a fixed dense state each stage (an "
                    "approximate reflecting obstacle: holding the state does not enforce an impermeable wall flux); an experimental erosion "
                    "rule can remove a block when the overpressure on an exposed face exceeds its strength.",
        "validation": "Analytical comparison for the solver: the Sod shock tube against the exact Riemann "
                       "solution (mean density error ≈ 0.003 at 300 cells, CI). The blast scenes themselves "
                       "are checked numerically (front deceleration toward the Sedov–Taylor exponent).",
        "demo": "results/explosion.gif"},
    "Shock Tube": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "Sod's shock tube: a membrane separates high-pressure gas from low-pressure gas; when it "
                 "bursts a shock runs right, a contact discontinuity follows, and a rarefaction fan spreads left. "
                 "The exact Riemann solution is known, so this is the solver's quantitative check.",
        "eq": _EULER_EQ,
        "numerics": "Same finite-volume scheme (MUSCL + minmod, HLLC, SSP-RK2, γ = 1.4) on a one-dimensional "
                    "tube shown as a strip. Transmissive ends.",
        "validation": "Analytical comparison: density, velocity and pressure against the exact Riemann solution "
                      "(Toro), with the errors printed in the diagnostics."},
    "Shockwave Strike": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A planar shock wave travels through air and strikes a bubble of lighter "
                 "gas. Because the shock speeds up in the light gas, it bends and focuses, "
                 "and the misalignment of pressure and density gradients deposits vorticity "
                 "on the interface (the baroclinic mechanism) — rolling the bubble up into a "
                 "vortex pair. This shock-bubble / Richtmyer–Meshkov interaction is a key "
                 "model problem for supersonic mixing and inertial-confinement fusion.",
        "eq": _EULER_EQ,
        "numerics": "Same compressible finite-volume scheme (MUSCL + minmod, HLLC Riemann "
                    "solver, SSP-RK2, γ = 1.4). One or two circular bubbles of a chosen "
                    "density ratio sit in still air; the incoming flow is the exact "
                    "Rankine–Hugoniot post-shock state for the Mach number you set, so shock "
                    "strength and density contrast are both physical, tunable inputs.",
        "validation": "Qualitative demonstration; the solver itself is compared with the exact Sod "
                       "solution (see the Shock Tube scene).",
        "demo": "results/shock_bubble.gif"},
    "The Big Splash": {"method": "Free-surface water · Smoothed-Particle Hydrodynamics",
        "blurb": "Free-surface water from one mesh-free solver: still water, a dam break, a water-blob "
                 "impact, a sloshing tank, a pouring stream, a flat-bottomed wave tank and a floating hull. "
                 "The fluid is a set of moving particles, so breaking and folding surfaces need no "
                 "interface tracking. Two-dimensional, weakly compressible, no surface tension.",
        "eq": r"$\dfrac{D\mathbf{v}_i}{Dt}=-\sum_j m_j\!\left(\dfrac{p_i}{\rho_i^2}+\dfrac{p_j}{\rho_j^2}+\Pi_{ij}\right)\nabla W_{ij}+\mathbf{g}$",
        "numerics": "Weakly-compressible SPH: each particle carries mass and velocity; "
                    "density and forces are smoothed sums over neighbours using a cubic-"
                    "spline kernel. Pressure follows a stiff Tait equation of state (clamped "
                    "≥ 0 to avoid the free-surface tensile instability), with Monaghan "
                    "artificial viscosity and a uniform background grid for fast neighbour "
                    "search. The walls are dynamic boundary particles — fixed layers of "
                    "particles that develop pressure through the same equation of state when "
                    "the fluid presses on them, so the wall pushes back with real pressure "
                    "(no penalty force on the fluid, no spurious near-wall motion); the "
                    "wavemaker is simply a wall layer that moves. A δ-SPH density-diffusion "
                    "term and XSPH velocity smoothing damp the acoustic noise and relax the "
                    "initial lattice; the floating hull is a rigid body driven by contact forces from "
                    "the fluid, gravity and damping, with limits on its motion.",
        "validation": "Numerical checks: still water stays at rest to a small residual (tests/); the "
                       "dam-break front lags the frictionless Ritter bound 2√(gH) as a collapsing column "
                       "should. The other scenes are qualitative demonstrations.",
        "demo": "results/dam_break.gif"},
    "Cloud Billows": {"method": "Pseudo-spectral · FFT",
        "blurb": "Two fluid streams sliding past each other at different speeds form an "
                 "unstable shear layer: ripples on the interface grow and roll up into a row "
                 "of spiral 'billows' that pair and merge, cascading toward two-dimensional "
                 "turbulence. The Kelvin–Helmholtz instability paints the billow clouds in "
                 "the sky, the bands of Jupiter, and the mixing layers in oceans and "
                 "engines. It is solved here with a high-accuracy spectral method.",
        "eq": r"$\partial_t\omega+(\mathbf{u}\!\cdot\!\nabla)\omega=\nu\nabla^2\omega,\qquad \nabla^2\psi=-\omega$",
        "numerics": "A pseudo-spectral vorticity–streamfunction formulation on a periodic "
                    "box: every spatial derivative is taken in Fourier space via the FFT, the "
                    "nonlinear advection term is formed in physical space with 2/3-rule "
                    "dealiasing, and time advances with classical fourth-order Runge–Kutta "
                    "(stable for the advection operator's imaginary eigenvalues).",
        "validation": "Analytical comparison: the Taylor–Green vortex decays as exp(−4νt) (relative "
                       "error ≈ 10⁻¹⁵ in tests/). Spatial derivatives are spectral but time stepping is "
                       "explicit RK4, so with ν = 0 the energy is conserved to truncation error "
                       "(measured drift ≈ 2×10⁻⁹ over 200 steps), not to round-off.",
        "demo": "results/turbulence.gif"},
    "Turing Patterns": {"method": "Reaction–Diffusion · Gray–Scott",
        "blurb": "Two chemicals diffuse at different rates while one feeds on the other. From a "
                 "nearly uniform start, that simple competition spontaneously organises into "
                 "spots, stripes, mazes and self-replicating blobs — the mechanism Alan Turing "
                 "proposed in 1952 for how a featureless embryo becomes a patterned animal. A "
                 "small change in the feed/kill rates switches the whole morphology.",
        "eq": r"$\partial_t U = D_u\nabla^2U - UV^2 + F(1-U),\ \ \partial_t V = D_v\nabla^2V + UV^2 - (F{+}k)V$",
        "numerics": "Explicit time stepping of the two coupled reaction–diffusion equations on a "
                    "periodic grid, with a 9-point isotropic Laplacian for the diffusion term. "
                    "The (F, k) pair is taken from Pearson's classification to select each regime.",
        "validation": "Numerical check: the (F, k) values yield the morphologies of Pearson's "
                       "classification. The scheme clips U and V to [0, 1] each step, so bounded "
                       "concentrations are enforced, not demonstrated. The resemblance to biological "
                       "patterns is suggestive only.",
        "demo": "results/gallery/rd_spots.gif"},
    "Quantum Ripples": {"method": "Schrödinger · split-step Fourier (experimental module, not in the gallery)",
        "blurb": "A quantum particle isn't a dot but a wave of probability. Launch a wavepacket "
                 "and watch it spread, tunnel through a wall it classically could not cross, "
                 "interfere with itself through a double slit, or slosh coherently in a trap. "
                 "The glow is |ψ|² — where the particle is likely to be found.",
        "eq": r"$i\hbar\,\partial_t\psi = -\tfrac{\hbar^2}{2m}\nabla^2\psi + V(\mathbf{x})\,\psi$",
        "numerics": "The time-dependent Schrödinger equation by the split-step Fourier method: "
                    "a half-step potential phase kick, a full kinetic step applied as a diagonal "
                    "multiply in Fourier space (FFT), then another half potential kick. The split "
                    "is second-order accurate and exactly unitary; a soft absorbing border lets "
                    "scattered waves leave without reflecting.",
        "validation": "Because every step is unitary the total probability ∫|ψ|² is conserved to "
                       "round-off (≈ 10⁻¹⁴ drift in the closed harmonic well) — shown live in the "
                       "run info.",
        "demo": "results/gallery/qm_barrier.gif"},
    "Ink in Motion": {"method": "Chaotic mixing · spectral + passive scalar",
        "blurb": "Drop bands of dye into a turbulent flow and watch them stretch and fold into "
                 "ever-finer filaments — the route by which stirring mixes things long before "
                 "molecular diffusion could. The same chaotic advection mixes cream into coffee, "
                 "pollutants into the ocean, and plankton blooms across the sea surface.",
        "eq": r"$\partial_t c + (\mathbf{u}\!\cdot\!\nabla)c = \kappa\nabla^2 c$",
        "numerics": "The turbulent velocity comes from the same spectral vorticity solver; the "
                    "dye is a passive scalar advected by it with periodic bilinear semi-Lagrangian "
                    "transport (unconditionally stable) and a touch of spectral diffusion.",
        "validation": "Bilinear semi-Lagrangian advection is unconditionally stable and nearly "
                       "monotone — the dye stays within [0, 1] as the filaments thin (interpolation "
                       "is slightly diffusive, so a little contrast is lost rather than gained), the "
                       "signature of stirring-dominated mixing.",
        "demo": "results/gallery/mix_bands.gif"},
    "Tracer in Rock": {"method": "Pore-scale Lattice-Boltzmann · advection–dispersion",
        "blurb": "Release a dye into water moving through rock and it does not travel as a neat block. "
                 "Wide channels run ahead, narrow ones lag, dead ends hold tracer back, and molecular "
                 "diffusion smears what is left. The result is a plume that spreads far faster than "
                 "diffusion alone would manage, and an arrival curve with a long tail. This is how "
                 "contaminants travel in groundwater and how tracer tests read a reservoir.",
        "eq": r"$\partial_t c + \nabla\!\cdot(\mathbf{u}c) = \nabla\!\cdot(D_m \nabla c)$",
        "numerics": "The pore flow is solved first with the same lattice-Boltzmann scheme as the porous "
                    "experiment and then held fixed (the pore Reynolds number is far below one, so the "
                    "field does not change while the tracer crosses). The tracer is advanced with a "
                    "finite-volume scheme on the same grid: upwind advective fluxes, a five-point "
                    "diffusive flux, and no flux at all through faces touching a grain, so none enters the "
                    "solid. Along the flow the periodic link of the flow solver is cut: the outlet is open, so "
                    "tracer leaves with the water and never re-enters, and the tracer is accounted for exactly "
                    "as injected = left + still inside. The breakthrough curve is the flux-averaged "
                    "concentration at the outlet face. The step obeys both the Courant and the diffusive "
                    "limits. Only molecular diffusion D_m is prescribed, from the Péclet number; the extra "
                    "spreading is produced by the velocity field itself.",
        "validation": "Analytical comparison: with the flow switched off the plume variance grows as 2·D_m·t "
                      "to four decimal places, and the tracer balance (injected = left + still inside) closes to "
                      "round-off with grains present and an open outlet (tests/). First-order upwind advection adds a numerical diffusivity of about u·dx/2, "
                      "which is reported next to the measured spreading; the measured dispersion is only "
                      "meaningful when it exceeds that number.",
        "demo": "results/gallery/tracer_pulse.gif"},
    "Porous Flow": {"method": "Pore-scale Lattice-Boltzmann · Darcy",
        "blurb": "Push fluid through a packed bed of grains and it threads a tortuous path "
                 "between them. Averaged over the sample, the flow rate is simply proportional to "
                 "the driving force — Darcy's law — and the constant of proportionality is the "
                 "permeability k, the single number that says how easily a rock, soil or filter "
                 "lets fluid through. Funoos resolves the pore-scale flow and measures k directly.",
        "eq": r"$\langle\mathbf{u}\rangle = -\tfrac{k}{\mu}\nabla p$",
        "numerics": "The same D2Q9 lattice-Boltzmann scheme, here in a periodic box driven by a "
                    "constant body force (Guo forcing) through a random grain pack, in the "
                    "viscous (Stokes) regime, along x or y. Permeability is k = ν U_D/g with U_D the "
                    "superficial velocity (flow averaged over the whole sample, solids counting as zero) "
                    "and g the body force per unit mass; the pore-average velocity U_D/φ is reported separately.",
        "validation": "Numerical check: the solver reproduces the analytical plane-Poiseuille permeability "
                       "(error 0.07 %), and k rises with porosity (CI). The Kozeny–Carman relation is an "
                       "empirical 3-D packed-bed formula shown for orientation only.",
        "demo": "results/gallery/porous_phi60.gif"},
}


def solver_versions():
    """Provenance of the native solvers: source hash + binary size (for saved experiments)."""
    import hashlib
    out = {}
    for d, n in (("lbm", "lbm2d"), ("incompressible", "ins2d"), ("compressible", "euler2d"), ("sph", "sph2d")):
        src = SOLVERS / d / (n + ".cpp"); b = _bin(d, n)
        rec = {}
        if src.exists():
            rec["source_sha256"] = hashlib.sha256(src.read_bytes()).hexdigest()[:16]
        if b.exists():
            rec["binary_bytes"] = b.stat().st_size
        out[n] = rec
    return out


def estimate(name, params):
    """Grid, frame count, memory and a rough wall-time estimate for a run (before it starts).

    Time scales are per-cell-step costs measured on the profiling machine (8 threads);
    they are indicative, not a promise — the UI labels them as estimates.
    """
    spec = EXHIBITS[name]
    p = {q["name"]: q["default"] for q in spec["params"]}; p.update(params or {})
    s = _res(p); dur = _durv(p)
    if name == "Wind Tunnel":
        nx, ny = int(900 * s), int(300 * s); steps = int(44000 * dur); frames = 90; comp = 2
        secs = nx * ny * steps * 2.0e-9
    elif name == "Porous Flow":
        nx, ny = int(380 * s), int(360 * s); steps = int(24000 * dur); frames = 70; comp = 2
        secs = nx * ny * steps * 2.0e-9
    elif name in ("Rising Smoke", "Candle Flame", "Mushroom Clouds", "Rayleigh-Benard", "Chimney Plume"):
        dims = {"Rising Smoke": (280, 440), "Mushroom Clouds": (280, 440), "Rayleigh-Benard": (480, 230),
                "Candle Flame": (190, 360), "Chimney Plume": (540, 420)}[name]
        nx, ny = int(dims[0] * s), int(dims[1] * s); steps = int(4800 * dur); frames = 100; comp = 3
        secs = nx * ny * steps * 1.6e-8
    elif name == "Detonation":
        nx = ny = int(420 * s); frames = 100; comp = 3; steps = int(70 * dur * nx * 0.9)
        secs = nx * ny * steps * 4.0e-9
    elif name == "Shockwave Strike":
        nx, ny = int(620 * s), int(320 * s); frames = 100; comp = 3; steps = int(230 * dur * nx * 0.4)
        secs = nx * ny * steps * 4.0e-9
    elif name == "The Big Splash":
        npart = max(500.0, float(p.get("particles", 3000))); nx, ny = int(np.sqrt(npart)), int(np.sqrt(npart))
        frames = 100; comp = 3; steps = int(9000 * dur)
        secs = npart * steps * 2.5e-7
    elif name in ("Cloud Billows", "Ink in Motion"):
        nx = ny = int(256 * s); frames = 95; comp = 2 if name == "Cloud Billows" else 1
        steps = int(2800 * dur * s); secs = nx * ny * np.log2(nx) * steps * 1.2e-8
    elif name == "Shock Tube":
        nx, ny = int(600 * s), 24; frames = 100; comp = 3; steps = int(0.2 * nx * dur * nx * 0.5)
        secs = nx * ny * steps * 4.0e-9
    else:                                             # Turing / quantum
        nx = ny = int(220 * s); frames = 110; comp = 1; steps = int(9000 * dur)
        secs = nx * ny * steps * 6e-9
    bytes_ = nx * ny * 4 * comp * frames
    return {"exhibit": name, "grid": [nx, ny], "steps": steps, "frames": frames,
            "bytes": int(bytes_), "mb": round(bytes_ / 2 ** 20, 1), "seconds": float(max(1.0, secs)),
            "threads": _ENV.get("OMP_NUM_THREADS")}


TMP_PREFIX = f"funoos-{os.getpid()}-"     # solver scratch dirs; stale ones are swept at the next launch


def solve_exhibit(name, params, progress=lambda s: None, cancel=None):
    """Run the solver once; return a Result you can .render(view, colormap) from.

    `cancel` (threading.Event) makes the solve cooperative: every progress report
    checks it and raises `Cancelled`; C++ solvers are killed by `_run_solver`.
    The scratch directory is removed whether the solve completes, fails or is
    cancelled.
    """
    spec = EXHIBITS[name]
    full = {q["name"]: q["default"] for q in spec["params"]}
    full.update(params or {})

    def pr(msg):
        if cancel is not None and cancel.is_set():
            raise Cancelled()
        progress(msg)
    pr.cancel = cancel
    with tempfile.TemporaryDirectory(prefix=TMP_PREFIX) as tmp:
        return spec["solve"](full, pr, tmp)


def run_exhibit(name, params, progress=lambda s: None, view=None, colormap=None):
    """Convenience: solve and render the default (or given) view. Used by demos."""
    r = solve_exhibit(name, params, progress)
    return r.render(view, colormap), r.info
