"""Record a walkthrough of the real Funoos UI in headless Chromium (Path 2).

Serves the app over HTTP, injects a faithful mock of window.pywebview.api backed
by the real data/media from prep_demo.py, then drives Home -> Gallery -> Detail
-> Studio -> Run -> switch views -> recolour -> diagnostics while recording video.
Output: results/_demo/rec/<hash>.webm  (path printed at the end).
"""
import json, functools, threading, sys
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from playwright.sync_api import sync_playwright

ROOT = Path("/home/impres/Saleh/FlowZoo")
demo = ROOT / "results" / "_demo"
PORT = 8137
W, H = 1920, 1080

CAT = json.load(open(demo / "catalog.json"))
DET = json.load(open(demo / "detail.json"))
RUN = json.load(open(demo / "run.json"))
DIAG = json.load(open(demo / "diag.json"))

INIT = """
window.__CAT = __CAT_JSON__; window.__DET = __DET_JSON__; window.__RUN = __RUN_JSON__; window.__DIAG = __DIAG_JSON__;
const sleep = ms => new Promise(r => setTimeout(r, ms));
window.pywebview = { api: {
  catalog: () => Promise.resolve(window.__CAT),
  scene_detail: (k) => Promise.resolve(window.__DET),
  run: async (ex, p, view, cmap) => {
    for (const pc of [12, 38, 66, 90, 100]) { window.onProgress && window.onProgress('simulating… ' + pc + '%'); await sleep(280); }
    window.onProgress && window.onProgress('rendering…'); await sleep(300);
    const R = window.__RUN;
    return { run_id: R.run_id, video: R.video, views: R.views, view: R.view,
             info: R.info, cmaps: R.cmaps, defcmap: R.defcmap, stats: R.stats };
  },
  render_view: async (rid, view, cmap) => {
    await sleep(260); const R = window.__RUN;
    const clip = R.clips[view + '|' + cmap] || R.clips[view + '|' + R.defcmap] || R.video;
    return { video: clip, view };
  },
  diagnostics: () => Promise.resolve(window.__DIAG),
  save_clip: () => Promise.resolve(null),
}};
""".replace("__CAT_JSON__", json.dumps(CAT)).replace("__DET_JSON__", json.dumps(DET)) \
   .replace("__RUN_JSON__", json.dumps(RUN)).replace("__DIAG_JSON__", json.dumps(DIAG))


def serve():
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), handler)
    httpd.log_message = lambda *a, **k: None
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    serve()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=[
            "--autoplay-policy=no-user-gesture-required", "--no-sandbox",
            "--disable-gpu", "--force-color-profile=srgb"])
        ctx = browser.new_context(viewport={"width": W, "height": H},
                                  record_video_dir=str(demo / "rec"),
                                  record_video_size={"width": W, "height": H})
        pg = ctx.new_page()
        pg.goto(f"http://127.0.0.1:{PORT}/index.html")
        # inject the API + fire pywebviewready AFTER load (like real pywebview), so
        # boot() runs once the whole script is parsed (avoids const/TDZ errors)
        pg.evaluate(INIT + "\nwindow.dispatchEvent(new Event('pywebviewready'));")
        pg.wait_for_selector(".gcard", state="attached", timeout=15000)

        def dwell(ms): pg.wait_for_timeout(ms)

        # 1) HOME — let the wordmark + counters animate
        dwell(3800)

        # 2) GALLERY — open, scroll the card grid
        pg.click('.railbtn[data-view="gallery"]'); dwell(1200)
        pg.evaluate("document.querySelector('#gallery-scroll').scrollTo({top:600,behavior:'smooth'})"); dwell(1500)
        pg.evaluate("document.querySelector('#gallery-scroll').scrollTo({top:1300,behavior:'smooth'})"); dwell(1500)
        pg.evaluate("document.querySelector('#gallery-scroll').scrollTo({top:0,behavior:'smooth'})"); dwell(900)

        # 3) DETAIL — open the Kármán scene, scroll past equation + write-up
        pg.click('.gcard:has-text("Kármán")'); dwell(2200)
        pg.evaluate("document.querySelector('#d-text').scrollTo({top:420,behavior:'smooth'})"); dwell(1800)
        pg.evaluate("document.querySelector('#d-text').scrollTo({top:900,behavior:'smooth'})"); dwell(1600)

        # 4) STUDIO — open, run
        pg.click('#d-open'); dwell(1400)
        pg.click('#s-run'); dwell(2600)                    # progress bar fills, result plays

        # 5) SWITCH VIEWS — same run, different visualisation
        for v in ["Velocity", "Streamlines", "Vorticity"]:
            pg.click(f'#s-views button:has-text("{v}")'); dwell(1900)

        # 6) RECOLOUR
        pg.select_option('#s-cmap', 'Inferno'); dwell(1800)
        pg.select_option('#s-cmap', 'Ocean (water)'); dwell(1700)

        # 7) DIAGNOSTIC PLOTS
        pg.click('#s-plots'); dwell(1500)
        pg.evaluate("document.querySelector('#s-plotpanel').scrollTo({top:380,behavior:'smooth'})"); dwell(2200)

        video = pg.video
        ctx.close(); browser.close()
        path = video.path() if video else None
        print("VIDEO:", path, flush=True)


if __name__ == "__main__":
    main()
