"""Layout check of the real Funoos page in Chromium at common window sizes.

Serves index.html with the real backend behind a small HTTP bridge (the same Api the desktop
window uses), runs one simulation, then resizes the window through the sizes below and measures
the gallery, the detail page and the Studio. Checks that fail make the script exit non-zero.

    python tools/check_layout.py                 # checks only
    python tools/check_layout.py --shots DIR     # also saves a screenshot per size and page

Needs:  python -m pip install playwright && python -m playwright install chromium

Sizes are the usable area inside the app window (CSS pixels), from the resolution statistics and
device defaults summarised in docs/ui_layout.md.
"""
import argparse
import json
import os
import sys
import threading
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SIZES = [
    ("app minimum 1024x640", 1024, 640),
    ("Windows 1080p at 150% 1280x641", 1280, 641),
    ("Windows 1366x768 1366x689", 1366, 689),
    ("app default 1440x870", 1440, 870),
    ("MacBook Air 13in 1470x900", 1470, 900),
    ("MacBook Pro 14in 1512x930", 1512, 930),
    ("Windows 1080p at 125% 1536x785", 1536, 785),
    ("MacBook Air 15in 1710x1050", 1710, 1050),
    ("MacBook Pro 16in 1728x1065", 1728, 1065),
    ("PC 1080p 1920x1001", 1920, 1001),
    ("PC 1440p 2560x1361", 2560, 1361),
]

GALLERY = r"""(() => {
  const vw = innerWidth, vh = innerHeight, R = e => e.getBoundingClientRect();
  const cards = [...document.querySelectorAll('#gallery-start .gcard:not([hidden]), #gallery-grid .gcard')];
  const full = cards.filter(c => R(c).top >= 0 && R(c).bottom <= vh).length;
  let clipped = 0, overlaps = 0;
  for (const c of cards) {
    const t = c.querySelector('.ttl'); if (t && t.scrollWidth > t.clientWidth + 1) clipped++;
    const fav = c.querySelector('.favbtn'), meta = c.querySelector('.gmeta');
    if (fav && meta) { const a = R(fav), b = R(meta); if (a.bottom > b.top && a.top < b.bottom && a.right > b.left && a.left < b.right) overlaps++; }
  }
  const chips = document.querySelector('#g-phen');
  return { cardsFullyVisible: full, clippedTitles: clipped, overlaps, pageOverflowX: document.querySelector('#gallery-scroll').scrollWidth > document.querySelector('#gallery-scroll').clientWidth + 1,
           chipsRows: chips ? Math.round(R(chips).height / 30) : 0 };
})()"""

DETAIL = r"""(() => {
  const vh = innerHeight, R = e => e.getBoundingClientRect();
  const shares = [...document.querySelectorAll('#d-text .layer .read.body')].filter(b => R(b).width > 0).map(b => {
    const rg = document.createRange(); rg.selectNodeContents(b); const rs = [...rg.getClientRects()];
    if (!rs.length) return 1; const w = Math.max(...rs.map(r => r.right)) - Math.min(...rs.map(r => r.left));
    return w / R(b).width; });
  shares.sort((a, b) => a - b);
  const longest = shares.length ? shares[shares.length - 1] : 1;
  const open = R(document.querySelector('#d-open'));
  return { textShareOfBox: +longest.toFixed(2), openButtonVisible: open.bottom <= vh + 1 };
})()"""

STUDIO = r"""(() => {
  const vw = innerWidth, vh = innerHeight, R = e => e.getBoundingClientRect();
  const dash = document.querySelector('#s-dash'), params = document.querySelector('#s-params');
  function visibleBand(e) { let t = 0, b = vh, p = e.parentElement; while (p && p !== document.documentElement) { const s = getComputedStyle(p); if (/(auto|scroll|hidden)/.test(s.overflowY)) { const q = R(p); t = Math.max(t, q.top); b = Math.min(b, q.bottom); } p = p.parentElement; } return { t, b }; }
  const ctrls = [...params.querySelectorAll('input, select')].filter(e => R(e).width > 0);
  const shown = ctrls.filter(e => { const a = R(e), v = visibleBand(e); return a.top >= v.t - 1 && a.bottom <= v.b + 1; }).length;
  const run = R(document.querySelector('#s-run')), band = visibleBand(document.querySelector('#s-run'));
  const bar = document.querySelector('.viewbar'); const kids = [...bar.children].filter(k => R(k).width > 0);
  const mids = kids.map(k => (R(k).top + R(k).bottom) / 2); const rows = mids.length ? (Math.max(...mids) - Math.min(...mids) > 14 ? 2 : 1) : 0;   // a wrapped item sits a whole row lower
  const stage = R(document.querySelector('#s-screen')), strip = R(document.querySelector('#s-kpis')), tr = R(document.querySelector('#studio .t-transport'));
  const v = document.querySelector('#s-video'); let field = 0;
  if (v.videoWidth && R(v).width) { const vr = R(v); const s = Math.min(vr.width / v.videoWidth, vr.height / v.videoHeight); field = v.videoWidth * s * v.videoHeight * s / (vw * vh); }
  return { controls: ctrls.length, controlsFullyVisible: shown, runVisible: run.top >= band.t - 1 && run.bottom <= band.b + 1,
           dashOverflowX: dash.scrollWidth > dash.clientWidth + 1, stageRight: Math.round(stage.right), toolbarRows: rows,
           stripInWindow: strip.bottom <= vh + 1 && strip.right <= vw + 1, transportInWindow: tr.bottom <= vh + 1 && tr.right <= vw + 1,
           stageShare: +(stage.width * stage.height / (vw * vh)).toFixed(2), fieldShare: +field.toFixed(3), vw, vh };
})()"""

BRIDGE = ("window.pywebview = { api: new Proxy({}, { get: (_, name) => (...args) => fetch('/api/' + String(name), "
          "{ method: 'POST', body: JSON.stringify(args) }).then(r => r.json()) }) };")


def serve(api, port):
    class H(SimpleHTTPRequestHandler):
        def __init__(self, *a, **k):
            super().__init__(*a, directory=str(ROOT), **k)

        def log_message(self, *a):
            pass

        def do_POST(self):
            name = self.path.rsplit("/", 1)[-1]; n = int(self.headers.get("Content-Length", 0))
            args = json.loads(self.rfile.read(n) or b"[]")
            try:
                r = getattr(api, name)(*args)
            except Exception as e:                      # noqa: BLE001
                r = {"ok": False, "error": f"{type(e).__name__}: {e}"}
            b = json.dumps(r, default=str).encode()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

    srv = ThreadingHTTPServer(("127.0.0.1", port), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def checks(size, w, h, g, d, s, sp):
    fails = []
    need = lambda ok, msg: None if ok else fails.append(f"{size}: {msg}")   # noqa: E731
    need(not g["pageOverflowX"], "gallery scrolls horizontally")
    need(g["cardsFullyVisible"] >= 3, f"only {g['cardsFullyVisible']} gallery cards fully visible on the first screen")
    need(g["clippedTitles"] == 0, f"{g['clippedTitles']} card titles clipped")
    need(g["overlaps"] == 0, f"{g['overlaps']} cards where the favourite button overlaps the metadata")
    need(d["textShareOfBox"] >= 0.8, f"detail text uses only {d['textShareOfBox']:.0%} of its box")
    need(d["openButtonVisible"], "Open in Studio is below the window")
    for name, st in (("studio", s), ("studio plots", sp)):
        need(not st["dashOverflowX"], f"{name}: a column is pushed out of the window")
        need(st["stageRight"] <= w + 1, f"{name}: the stage extends past the window")
        need(st["toolbarRows"] == 1, f"{name}: the stage toolbar wraps")
        need(st["runVisible"], f"{name}: Run is not visible")
        need(st["stripInWindow"] and st["transportInWindow"], f"{name}: readouts or transport outside the window")
    need(s["controlsFullyVisible"] >= min(s["controls"], 4 if h >= 700 else 3),
         f"only {s['controlsFullyVisible']} of {s['controls']} controls visible without scrolling")
    need(s["fieldShare"] >= 0.12, f"the field covers only {s['fieldShare']:.0%} of the window")
    return fails


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", default=None)
    ap.add_argument("--port", type=int, default=8190)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()
    import funoos_app
    from playwright.sync_api import sync_playwright
    api = funoos_app.Api(sweep=False)
    serve(api, args.port)
    shots = Path(args.shots) if args.shots else None
    if shots:
        shots.mkdir(parents=True, exist_ok=True)
    rows, fails = [], []
    with sync_playwright() as p:
        b = p.chromium.launch(headless=True, args=["--no-sandbox", "--autoplay-policy=no-user-gesture-required"])
        pg = b.new_page(viewport={"width": 1440, "height": 870}); pg.add_init_script(BRIDGE)
        errors = []; pg.on("pageerror", lambda e: errors.append(str(e)))
        pg.goto(f"http://127.0.0.1:{args.port}/index.html"); pg.wait_for_selector(".gcard", state="attached", timeout=60000)
        pg.evaluate("openDetail('lbm_airfoil')"); pg.wait_for_timeout(1500); pg.click("#d-open"); pg.wait_for_timeout(1200)
        pg.evaluate("(() => { const s = [...document.querySelectorAll('#s-params select')].find(x => [...x.options].some(o => o.value === 'Low (fast)')); s.value = 'Low (fast)'; s.dispatchEvent(new Event('change', { bubbles: true })); })()")
        pg.wait_for_timeout(500); pg.click("#s-run")
        pg.wait_for_function("document.querySelector('#s-video').style.display === 'block' && !document.querySelector('#s-run').disabled", timeout=600000)
        pg.wait_for_timeout(1500)
        for size, w, h in SIZES:
            pg.set_viewport_size({"width": w, "height": h})
            pg.evaluate("show('gallery')"); pg.wait_for_timeout(700)
            g = pg.evaluate(GALLERY)
            if shots:
                pg.screenshot(path=str(shots / f"{w}x{h}_gallery.png"))
            pg.evaluate("openDetail('lbm_airfoil')"); pg.wait_for_timeout(900)
            d = pg.evaluate(DETAIL)
            if shots:
                pg.screenshot(path=str(shots / f"{w}x{h}_detail.png"))
            pg.evaluate("show('studio'); setTab('field')"); pg.wait_for_timeout(900)
            s = pg.evaluate(STUDIO)
            if shots:
                pg.screenshot(path=str(shots / f"{w}x{h}_studio.png"))
            pg.evaluate("setTab('plots')"); pg.wait_for_timeout(1500)
            sp = pg.evaluate(STUDIO)
            if shots:
                pg.screenshot(path=str(shots / f"{w}x{h}_plots.png"))
            pg.evaluate("setTab('field')")
            f = checks(size, w, h, g, d, s, sp)
            fails += f
            rows.append({"size": size, "gallery": g, "detail": d, "studio": s, "plots": sp, "failures": f})
            print(f"{'ok  ' if not f else 'FAIL'} {size:34s} controls {s['controlsFullyVisible']}/{s['controls']}  toolbar rows {s['toolbarRows']}"
                  f"  stage {s['stageShare']:.2f}  field {s['fieldShare']:.2f}  cards {g['cardsFullyVisible']}  detail text {d['textShareOfBox']:.2f}", flush=True)
        b.close()
    if errors:
        fails += [f"page error: {e}" for e in errors]
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=1))
    for f in fails:
        print("  -", f)
    print(f"{len(SIZES)} sizes, {len(fails)} failed checks")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
