"""Generate real backend data + media for the app-walkthrough promo (Path 2).

Solves the demo scene once with the actual engine, renders its views + a couple
of recolour variants, and dumps catalog/detail/run/diagnostics as JSON so a
mocked pywebview.api can serve authentic content to the real UI in a headless
browser. Output under results/_demo/.
"""
import json, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, "/home/impres/Saleh/FlowZoo")
import flowzoo.engine as E, flowzoo.render as R, flowzoo.postproc as P, flowzoo.catalog as C
import funoos_app

ROOT = Path("/home/impres/Saleh/FlowZoo")
demo = ROOT / "results" / "_demo"; demo.mkdir(parents=True, exist_ok=True)
api = funoos_app.Api()

# ---- catalog (mirror Api.catalog) ----
groups = []
for method, scenes in C.by_method().items():
    items = []
    for s in scenes:
        key = s["key"]; mp4 = ROOT / "results" / "gallery" / (key + ".mp4")
        items.append({"key": key, "name": s["name"], "blurb": s["blurb"], "exhibit": s["exhibit"],
                      "preset": s["preset"], "clip": ("results/gallery/" + key + ".mp4") if mp4.exists() else None})
    groups.append({"method": method, "scenes": items})
json.dump(groups, open(demo / "catalog.json", "w"))
print("catalog scenes:", sum(len(g["scenes"]) for g in groups), flush=True)

# ---- demo scene: Kármán vortex street (real detail payload) ----
KEY = "lbm_cylinder"
detail = api.scene_detail(KEY)
json.dump(detail, open(demo / "detail.json", "w"))
exhibit, preset = detail["exhibit"], detail["preset"]
params = {q["name"]: q["default"] for q in E.EXHIBITS[exhibit]["params"]}
params.update(preset or {}); params["resolution"] = "Medium"
print("solving demo…", flush=True)
res = E.solve_exhibit(exhibit, params)
views = list(res.views); defcmap = detail.get("cmap") or E.DEFCMAP[res.kind]
print("views:", views, "defcmap:", defcmap, flush=True)


def cn(v, cm): return (v + "__" + cm).replace(" ", "_").replace("(", "").replace(")", "").replace("/", "").replace("–", "-")


clips = {}
def save(v, cm):
    nm = cn(v, cm)
    R.save_mp4([np.asarray(f) for f in res.render(v, cm)], demo / (nm + ".mp4"), fps=26)
    clips[v + "|" + cm] = "results/_demo/" + nm + ".mp4"
    print("rendered", v, "·", cm, flush=True)


for v in views: save(v, defcmap)                       # each view in the default palette
for cm in ["Inferno", "Ocean (water)"]: save(views[0], cm)   # recolour variants of the first view

stats = funoos_app._stats(res, exhibit)
run = {"run_id": "demo", "views": views, "view": views[0], "info": res.info,
       "cmaps": list(R.COLORMAPS), "defcmap": defcmap, "stats": stats,
       "clips": clips, "video": clips[views[0] + "|" + defcmap]}
json.dump(run, open(demo / "run.json", "w"))
diag = [{"title": t, "img": funoos_app._b64_png(np.asarray(img)), "explain": ex} for t, img, ex in P.plots(res)]
json.dump(diag, open(demo / "diag.json", "w"))
print("DONE. clips:", list(clips.keys()), " diagnostics:", len(diag), flush=True)
