"""Record a walkthrough of the real Funoos page (for docs/funoos_app_promo.mp4).

The page is served with the real backend behind a local HTTP bridge (the same Api the
desktop window uses). The demo run is solved once before recording and its views and
palettes are encoded in advance, so the recording shows real results without waiting
for the solver: when Run is pressed the bridge plays a short progress sequence and returns
that run. Everything else (catalogue, details, diagnostics, explanations, run history)
is answered live.

    python tools/record_walkthrough.py [WORKDIR]      # WORKDIR default: results/_demo
Output: WORKDIR/rec/<hash>.webm (path printed at the end); build_app_promo.py wraps it.
Needs:  python -m pip install playwright && python -m playwright install chromium
"""
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
WORK = Path(sys.argv[1] if len(sys.argv) > 1 else os.environ.get("FUNOOS_PROMO_WORK", ROOT / "results" / "_demo"))
PORT = 8137
W, H = 1600, 900                        # CSS window (MacBook-like), rendered at 1.6x
DPR = 1.6
VW, VH = 2560, 1440                      # recorded video size
SCENE = "lbm_cylinder"
RESOLUTION = "High"
VIEWS_TO_SHOW = ["Speed", "Streamlines", "Vorticity"]
PALETTES = ["Inferno"]

HEADLINE = """
(() => {
  const hl = document.createElement('div'); hl.id = 'promoHL';
  hl.style.cssText = 'position:fixed;top:26px;left:50%;transform:translateX(-50%);z-index:99999;'
    + 'padding:10px 24px;border-radius:999px;background:rgba(10,19,34,.80);'
    + 'border:1px solid rgba(126,155,255,.42);color:#eaf0fb;pointer-events:none;'
    + 'font:600 24px/1 "DejaVu Sans",system-ui,sans-serif;letter-spacing:.3px;'
    + 'opacity:0;transition:opacity .45s ease;box-shadow:0 14px 50px rgba(0,0,0,.45);white-space:nowrap';
  document.body.appendChild(hl);
  window.__hl = t => { const e = document.getElementById('promoHL'); if (t === null) e.style.opacity = 0; else { e.textContent = t; e.style.opacity = 1; } };
})();
"""

BRIDGE = """
window.pywebview = { api: new Proxy({}, { get: (_, name) => async (...args) => {
  if (String(name) === 'run') {                       // short progress sequence, then the prepared real run
    const jobId = args[5];
    for (const pc of [8, 27, 49, 72, 91, 100]) { if (window.onProgress) window.onProgress('simulating… ' + pc + '%', jobId); await new Promise(r => setTimeout(r, 330)); }
    if (window.onProgress) window.onProgress('rendering…', jobId); await new Promise(r => setTimeout(r, 350));
  }
  const r = await fetch('/api/' + String(name), { method: 'POST', body: JSON.stringify(args) });
  return r.json();
} }) };
"""


def prepare(api):
    from flowzoo import catalog, engine
    sc = catalog.scene(SCENE)
    params = {q["name"]: q["default"] for q in engine.EXHIBITS[sc["exhibit"]]["params"]}
    params.update(sc["preset"]); params["resolution"] = RESOLUTION
    print("solving the demo run…", flush=True)
    r = api.run(sc["exhibit"], params, None, sc.get("cmap"), 26, "demo", False)
    assert r.get("ok"), r
    for v in r["views"]:
        for cm in [r["defcmap"]] + PALETTES:
            api.render_view("demo", v, cm, 26, None, "", "")
    api.diagnostics("demo", None)
    print("demo run ready:", r["info"], flush=True)
    return sc["exhibit"], r


def serve(api, cached):
    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]; n = int(self.headers.get("Content-Length", 0))
            args = json.loads(self.rfile.read(n) or b"[]")
            try:
                r = cached if name == "run" else getattr(api, name)(*args)
            except Exception as e:                      # noqa: BLE001
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            b = json.dumps(r, default=str).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()


def main():
    import funoos_app
    from playwright.sync_api import sync_playwright
    WORK.mkdir(parents=True, exist_ok=True)
    api = funoos_app.Api(sweep=False)
    _exhibit, cached = prepare(api)
    serve(api, cached)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=["--autoplay-policy=no-user-gesture-required", "--no-sandbox",
                                                           "--force-color-profile=srgb"])
        ctx = browser.new_context(viewport={"width": W, "height": H}, device_scale_factor=DPR, record_video_dir=str(WORK / "rec"),
                                  record_video_size={"width": VW, "height": VH})
        ctx.add_init_script("try { localStorage.clear(); } catch (e) {}")
        pg = ctx.new_page(); pg.add_init_script(BRIDGE)
        pg.goto(f"http://127.0.0.1:{PORT}/index.html")
        pg.wait_for_selector(".gcard", state="attached", timeout=60000)
        pg.evaluate(HEADLINE)
        dwell = pg.wait_for_timeout
        hl = lambda t: pg.evaluate("window.__hl(" + json.dumps(t) + ")")   # noqa: E731

        hl("Explore fluid motion through simulation"); dwell(3400)

        hl("28 experiments, 51 presets, six numerical methods")
        pg.click('.railbtn[data-view="gallery"]'); dwell(2200)
        pg.hover('#gallery-start .gcard >> nth=1'); dwell(1600)
        pg.click('#g-phen .chipbtn >> nth=5'); dwell(1700)
        pg.click('#g-phen .chipbtn >> nth=0'); dwell(900)
        pg.evaluate("document.querySelector('#gallery-scroll').scrollTo({top: 760, behavior: 'smooth'})"); dwell(1700)
        pg.evaluate("document.querySelector('#gallery-scroll').scrollTo({top: 0, behavior: 'smooth'})"); dwell(900)

        hl("Every experiment explains itself")
        pg.click('#gallery-start .gcard[aria-label^="Cylinder wake"]'); dwell(2300)
        pg.evaluate("document.querySelector('#d-text').scrollTo({top: 520, behavior: 'smooth'})"); dwell(1800)
        pg.evaluate("document.querySelector('#d-text').scrollTo({top: 0, behavior: 'smooth'})"); dwell(700)

        hl("Set up the experiment, then run it")
        pg.click("#d-open"); dwell(1500)
        more = pg.query_selector("#s-params .hmore")
        if more:
            more.click(); dwell(1300); more.click(); dwell(400)
        pg.click("#s-run"); dwell(3600)

        hl("Switch views while it plays")
        for v in VIEWS_TO_SHOW:
            pg.click(f'#s-views button:has-text("{v}")'); dwell(1900)

        hl("Recolour instantly")
        pg.select_option("#s-cmap", PALETTES[0]); dwell(1900)
        pg.select_option("#s-cmap", cached["defcmap"]); dwell(900)

        hl("Measurements beside the field")
        pg.click("#s-plots"); dwell(2600)
        pg.evaluate("document.querySelector('#s-plotpanel').scrollTo({top: 420, behavior: 'smooth'})"); dwell(1500)

        hl("The physics, the model and the checks")
        pg.click("#tab-explain"); dwell(2300)
        pg.click("#tab-field"); dwell(900)
        hl(None); dwell(300)

        video = pg.video
        ctx.close(); browser.close()
        print("VIDEO:", video.path() if video else None, flush=True)


if __name__ == "__main__":
    main()
