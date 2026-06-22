"""Funoos — desktop app (pywebview shell around the HTML/CSS/JS UI).

The C++/Python solvers are unchanged; this only swaps the presentation layer.
`Api` is the bridge the web UI calls (pywebview.api.*): it lists the catalog,
serves parameter specs + write-ups, and — on Run — solves once and encodes the
chosen view to an MP4 returned as a base64 data-URL (so there's no file server
to manage). Results are cached per run so view-switching and the diagnostics
plots are instant.

    pip install pywebview
    python funoos_app.py
"""
from __future__ import annotations

import base64
import io
import sys
import tempfile
import threading
import uuid
from pathlib import Path

ROOT = Path(getattr(sys, "_MEIPASS", str(Path(__file__).resolve().parent)))
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render, content, postproc, catalog   # noqa: E402


def _b64_png(rgb):
    from PIL import Image
    buf = io.BytesIO(); Image.fromarray(rgb).save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def _b64_mp4(frames, fps):
    with tempfile.TemporaryDirectory() as d:
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
        out.append({"l": "permeability k", "v": f"{h.get('permeability', 0):.2f}", "u": "cells²", "accent": True})
        out.append({"l": "porosity φ", "v": f"{h.get('porosity', 0):.2f}"})
    out.append({"l": "frames", "v": str(len(res.raw))})
    out.append({"l": "views", "v": str(len(res.views))})
    out.append({"l": "method", "v": meth})
    return out


class Api:
    def __init__(self):
        self._runs = {}          # run_id -> {result, views, info}
        self._win = None

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

    def scene_detail(self, key):
        s = catalog.scene(key)
        if not s:
            return {}
        ex = s["exhibit"]; m = engine.META.get(ex, {}); d = content.DETAIL.get(ex, {})
        return {"name": s["name"], "method": s["method"], "exhibit": ex,
                "blurb": s["blurb"], "physics": d.get("physics", m.get("blurb", "")),
                "terms": d.get("terms", ""), "numerics": m.get("numerics", ""),
                "validation": m.get("validation", ""), "eq": _eq_b64(ex),
                "clip": "results/gallery/" + key + ".mp4", "preset": s["preset"],
                "cmap": s.get("cmap"), "params": _param_spec(ex), "method_label": m.get("method", "")}

    # ---------- run / render ----------
    def run(self, exhibit, params, view, cmap=None, fps=26):
        def progress(msg):
            if self._win:
                try:
                    self._win.evaluate_js(f"window.onProgress && window.onProgress({_js(msg)})")
                except Exception:
                    pass
        res = engine.solve_exhibit(exhibit, params, progress=progress)
        view = view if view in res.views else res.views[0]
        cm = cmap if (cmap in render.COLORMAPS) else engine.DEFCMAP[res.kind]
        progress(f"rendering {view}…")
        vid = _b64_mp4(res.render(view, cm), fps)
        rid = uuid.uuid4().hex[:8]
        self._runs[rid] = {"result": res, "info": res.info}
        return {"run_id": rid, "video": vid, "views": list(res.views),
                "view": view, "info": res.info, "cmaps": list(render.COLORMAPS),
                "defcmap": cm, "stats": _stats(res, exhibit)}

    def render_view(self, run_id, view, cmap=None, fps=26):
        r = self._runs.get(run_id)
        if not r:
            return {"error": "run expired"}
        res = r["result"]; cm = cmap or engine.DEFCMAP[res.kind]
        return {"video": _b64_mp4(res.render(view, cm), fps), "view": view}

    def diagnostics(self, run_id):
        r = self._runs.get(run_id)
        if not r:
            return []
        return [{"title": t, "img": _b64_png(img)} for t, img in postproc.plots(r["result"])]


def _js(s):
    import json
    return json.dumps(s)


def main():
    try:
        import webview
    except Exception:
        print("pywebview not installed.  pip install pywebview\n"
              "(then: python funoos_app.py)")
        return
    api = Api()
    win = webview.create_window("Funoos — where imagination becomes vision",
                                str(ROOT / "index.html"), js_api=api,
                                width=1440, height=900, min_size=(1120, 720),
                                background_color="#0A1322")
    api._win = win
    webview.start(http_server=True)


if __name__ == "__main__":
    main()
