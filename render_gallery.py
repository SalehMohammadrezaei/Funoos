"""Render every gallery scene to a clip in results/gallery/.

    python render_gallery.py [resolution] [duration]
        resolution : Low (fast) | Medium | High | Ultra (slow)   (default High)
        duration   : simulation-length multiplier                (default 1.6)

Each scene from flowzoo/catalog.py is solved with its preset, rendered in its
default view, and written as <key>.gif (+ .mp4 if ffmpeg is available).
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import numpy as np
from PIL import Image
from flowzoo import engine, render, catalog


def _shrink(frames, maxw=640):
    """Downscale frames for a light-weight gallery GIF (the MP4 keeps full res)."""
    out = []
    for f in frames:
        im = Image.fromarray(f)
        if im.width > maxw:
            im = im.resize((maxw, int(im.height * maxw / im.width)), Image.LANCZOS)
        out.append(np.asarray(im))
    return out

OUT = ROOT / "results" / "gallery"
OUT.mkdir(parents=True, exist_ok=True)
RES = sys.argv[1] if len(sys.argv) > 1 else "High"
DUR = float(sys.argv[2]) if len(sys.argv) > 2 else 1.6
ONLY = set(sys.argv[3].split(",")) if len(sys.argv) > 3 else None   # optional key list

t_all = time.time(); failed = []
for s in catalog.SCENES:
    if ONLY and s["key"] not in ONLY:
        continue
    name, key = s["exhibit"], s["key"]
    params = {qd["name"]: qd["default"] for qd in engine.EXHIBITS[name]["params"]}
    params.update(s["preset"])
    if "resolution" in params:
        params["resolution"] = RES
    if "duration" in params:
        params["duration"] = DUR
    print(f"[{key}] {s['name']}  ({name}, res={RES}, dur={DUR})…", flush=True)
    t0 = time.time()
    try:
        res = engine.solve_exhibit(name, params)
        cmap = s.get("cmap") or engine.DEFCMAP[res.kind]
        frames = res.render(res.views[0], cmap)
        render.save_gif(_shrink(frames), OUT / f"{key}.gif", fps=26)   # light clip for the gallery
        render.save_mp4(frames, OUT / f"{key}.mp4", fps=26)            # the app needs the MP4: a failure is a failure
        import subprocess as _sp
        _sp.run([render._ffmpeg(), "-v", "error", "-y", "-ss", "0.5", "-i", str(OUT / f"{key}.mp4"), "-frames:v", "1", "-q:v", "4",
                 "-vf", "scale=480:-2", str(OUT / f"{key}.jpg")], check=True)   # poster for the gallery card
        if key in {e["representative"] for e in catalog.EXPERIMENTS}:           # card thumbnail (tools/make_thumbs.py)
            _sp.run([sys.executable, str(ROOT / "tools" / "make_thumbs.py"), key], check=True)
        print(f"   ✓ {len(frames)} frames in {time.time()-t0:.0f}s -> gallery/{key}.gif", flush=True)
    except Exception as e:
        failed.append(key); print(f"   ✗ FAILED: {e}", flush=True)
if failed:
    print(f"GALLERY INCOMPLETE: {len(failed)} scene(s) failed: {', '.join(failed)}", flush=True)
    sys.exit(1)
print(f"ALL GALLERY CLIPS DONE in {time.time()-t_all:.0f}s", flush=True)
