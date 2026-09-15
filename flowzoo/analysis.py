"""Point probes, line profiles, frame inspection and side-by-side comparison.

All functions take an `engine.Result`. Coordinates are fractions of the *field*
(0..1 from the left / bottom, matching the rendered image with +y up); frame
positions are fractions of the clip (0..1) or absolute simulation times.
"""
from __future__ import annotations

import numpy as np

from . import render


def field_shape(res):
    d = res.derived(res.views[0]) if res.kind != "particles" else None
    if d is not None and d.get("fields") is not None:
        return tuple(d["fields"][0].shape[:2])
    return None


def field_rect(res, view=None):
    """Where the field sits inside the rendered frame of `view`, as fractions
    {x0, y0, w, h} of the frame (y from the bottom), plus the field's cell shape.
    Uses the actual rendered frame size and the view's own field shape/upscale, so
    streamline upscaling and the SPH raster grid are represented correctly."""
    view = res.view_name(view)
    fr = res.frame(res.nframes - 1, view)                # one frame (cached derived fields; cheap)
    H, W = fr.shape[:2]
    d = res.derived(view)
    f = d.get("fields")
    if f is None:                                        # particle scatter views: the whole image is the tank
        return {"x0": 0.0, "y0": 0.0, "w": 1.0, "h": 1.0, "shape": None}
    fy, fx = np.asarray(f[len(f) - 1]).shape[:2]
    if view == "Streamlines":
        up = 2                                           # streamlines_fast renders at 2×
    else:
        up = d.get("upscale", 1)
    fw, fh = fx * up, fy * up
    return {"x0": 0.0, "y0": max(0.0, 1.0 - fh / H), "w": min(1.0, fw / W), "h": min(1.0, fh / H), "shape": [fy, fx]}


def panel_fraction(res, view=None):
    """Width fraction of the rendered frame NOT covered by the field (the colourbar panel)."""
    return 1.0 - field_rect(res, view)["w"]


def frame_index(res, when):
    """Frame index from a clip fraction (0..1) or an absolute time (> 1 or 'time' dict)."""
    n = res.nframes
    if isinstance(when, dict):
        if when.get("index") is not None:
            return int(when["index"]) % n
        t = float(when.get("time", 0.0)); return int(np.argmin(np.abs(np.asarray(res.times) - t)))
    f = float(when)
    return int(round(max(0.0, min(1.0, f)) * (n - 1)))


def value_at(res, view, xfrac, yfrac, when=1.0):
    """Value of the view's scalar field at a point (fractions of the field, +y up)."""
    d = res.derived(view)
    if d.get("fields") is None:
        raise ValueError("this view has no scalar field to inspect")
    i = frame_index(res, when)
    f = d["fields"][i]; ny, nx = f.shape[:2]
    ix = int(min(nx - 1, max(0, round(xfrac * (nx - 1))))); iy = int(min(ny - 1, max(0, round(yfrac * (ny - 1)))))
    v = float(f[iy, ix])
    solid = bool(res.mask is not None and np.asarray(res.mask)[iy, ix])
    return {"value": None if (solid or not np.isfinite(v)) else v, "label": d["label"], "ix": ix, "iy": iy,
            "index": i, "time": float(res.times[i]), "solid": solid, "empty": not np.isfinite(v)}


def probe_series(res, view, xfrac=None, yfrac=None, ix=None, iy=None):
    """Time series of the view's field at one point over all frames. Pass either field
    fractions or the resolved cell (ix, iy); the cell wins so display and export agree."""
    d = res.derived(view)
    if d.get("fields") is None:
        raise ValueError("this view has no scalar field to probe")
    f0 = d["fields"][0]; ny, nx = f0.shape[:2]
    if ix is None or iy is None:
        ix = int(min(nx - 1, max(0, round(xfrac * (nx - 1))))); iy = int(min(ny - 1, max(0, round(yfrac * (ny - 1)))))
    ix = int(min(nx - 1, max(0, ix))); iy = int(min(ny - 1, max(0, iy)))
    vals = [float(f[iy, ix]) for f in d["fields"]]
    return {"label": d["label"], "ix": ix, "iy": iy, "times": [float(t) for t in res.times],
            "values": [None if not np.isfinite(v) else v for v in vals],
            "time_unit": res.hints.get("time_unit", "frame")}


def line_profile(res, view, axis="x", frac=0.5, when=1.0, index=None, ix=None, iy=None):
    """Values along a horizontal (axis='x', at row iy / height frac) or vertical line
    (axis='y', at column ix / x frac) of frame `index` (or clip position `when`)."""
    d = res.derived(view)
    if d.get("fields") is None:
        raise ValueError("this view has no scalar field to profile")
    i = int(index) % res.nframes if index is not None else frame_index(res, when)
    f = d["fields"][i]; ny, nx = f.shape[:2]
    if axis == "x":
        iy = int(min(ny - 1, max(0, round(frac * (ny - 1))))) if iy is None else int(min(ny - 1, max(0, iy)))
        line = f[iy, :]; pos = np.linspace(0, 1, nx); at = {"iy": iy}
    else:
        ix = int(min(nx - 1, max(0, round(frac * (nx - 1))))) if ix is None else int(min(nx - 1, max(0, ix)))
        line = f[:, ix]; pos = np.linspace(0, 1, ny); at = {"ix": ix}
    return {"label": d["label"], "axis": axis, "pos": pos.tolist(),
            "values": [None if not np.isfinite(v) else float(v) for v in line], "index": i,
            "time": float(res.times[i]), **at}


def compare_check(a, b, view):
    """Are two results comparable in `view`? Same kind, same view available, same time unit."""
    va, vb = a.view_name(view), b.view_name(view)
    if a.kind != b.kind:
        return False, f"different solver families ({a.kind} vs {b.kind})"
    if va != vb or view not in a.views:
        return False, f"view {view!r} is not available for both runs"
    ua, ub = a.hints.get("time_unit", "frame"), b.hints.get("time_unit", "frame")
    if ua != ub:
        return False, f"different time units ({ua} vs {ub})"
    return True, ""


def compare_plan(a, b):
    """Time alignment over the SHARED interval only: the union of both frame times inside
    [max(t0), min(t1)], each mapped to its nearest frame in each run. No frame is repeated
    beyond a run's duration. Returns (times, ia, ib, note)."""
    ta = np.asarray(a.times, float); tb = np.asarray(b.times, float)
    lo, hi = max(ta[0], tb[0]), min(ta[-1], tb[-1])
    if hi < lo:
        return [], [], [], "the runs do not overlap in time"
    grid = np.union1d(ta[(ta >= lo) & (ta <= hi)], tb[(tb >= lo) & (tb <= hi)])
    ia = [int(np.argmin(np.abs(ta - t))) for t in grid]; ib = [int(np.argmin(np.abs(tb - t))) for t in grid]
    dta = float(np.median(np.diff(ta))) if len(ta) > 1 else 0.0; dtb = float(np.median(np.diff(tb))) if len(tb) > 1 else 0.0
    note = (f"shared interval [{lo:g}, {hi:g}] {a.hints.get('time_unit', '')}; each frame shows the nearest saved frame "
            f"of each run (frame spacing {dta:g} vs {dtb:g})")
    if lo > min(ta[0], tb[0]) or hi < max(ta[-1], tb[-1]):
        note += "; frames outside the shared interval are not shown"
    return grid.tolist(), ia, ib, note


def compare_frames(a, b, view, cmap, vmin=None, vmax=None, shared_scale=True):
    """Yield (frame, time) side by side over the shared interval (see compare_plan) with one
    colour range for both runs."""
    ok, why = compare_check(a, b, view)
    if not ok:
        raise ValueError("cannot compare: " + why)
    va, vb = a.view_name(view), b.view_name(view)
    grid, ia, ib, _note = compare_plan(a, b)
    if not grid:
        raise ValueError("cannot compare: the runs do not overlap in time")
    if shared_scale and vmin is None and vmax is None:
        na, nb = a.derived(va)["norm"], b.derived(vb)["norm"]
        vmin, vmax = min(na.vmin, nb.vmin), max(na.vmax, nb.vmax)
        if na.diverging or nb.diverging:
            m = max(abs(vmin), abs(vmax)); vmin, vmax = -m, m
    for k, (i, j) in enumerate(zip(ia, ib)):
        fa = a.frame(i, va, cmap, vmin, vmax); fb = b.frame(j, vb, cmap, vmin, vmax)
        H = max(fa.shape[0], fb.shape[0])

        def pad(f):
            if f.shape[0] == H:
                return f
            out = np.zeros((H, f.shape[1], 3), np.uint8); out[:] = np.array([10, 11, 18], np.uint8)
            out[:f.shape[0]] = f; return out
        yield np.concatenate([pad(fa), np.full((H, 6, 3), 40, np.uint8), pad(fb)], axis=1), float(grid[k]), (vmin, vmax)
