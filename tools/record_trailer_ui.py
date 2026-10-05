"""Record interface footage for the trailer from the real Funoos page (same bridge as
tools/record_walkthrough.py: the demo run is solved once, everything else is answered live).
Writes ui/rec/*.webm and ui/segments.json with the start and end time of every action."""
import json, os, sys, time
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]; sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / 'tools'))
import record_walkthrough as RW
WORK = Path(os.environ.get('FUNOOS_TRAILER_UI') or ROOT / 'results' / '_trailer' / 'ui')

CURSOR = """
(() => { const make = () => { if (document.getElementById('fakeCursor')) return;
  const c = document.createElement('div'); c.id = 'fakeCursor';
  c.style.cssText = 'position:fixed;left:0;top:0;width:22px;height:22px;margin:-11px 0 0 -11px;border-radius:50%;z-index:999999;'
    + 'pointer-events:none;border:2.5px solid rgba(255,196,120,.95);background:rgba(255,184,107,.28);'
    + 'box-shadow:0 0 14px rgba(255,184,107,.55);transition:transform .12s ease;';
  document.body.appendChild(c);
  window.addEventListener('mousemove', e => { c.style.left = e.clientX + 'px'; c.style.top = e.clientY + 'px'; }, true);
  window.addEventListener('mousedown', () => { c.style.transform = 'scale(.6)'; }, true);
  window.addEventListener('mouseup', () => { c.style.transform = 'scale(1)'; }, true); };
  if (document.body) make(); else document.addEventListener('DOMContentLoaded', make); })();
"""

def main():
    import funoos_app
    from playwright.sync_api import sync_playwright
    WORK.mkdir(parents=True, exist_ok=True)
    api = funoos_app.Api(sweep=False)
    _ex, cached = RW.prepare(api); RW.serve(api, cached)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True, args=['--autoplay-policy=no-user-gesture-required', '--no-sandbox', '--force-color-profile=srgb'])
        # the screencast is one video pixel per CSS pixel whatever the device scale factor, so the window is
        # 1920x1080 and the page is zoomed 1.25x: a 1536x864 layout drawn large and sharp, filling the frame
        ctx = browser.new_context(viewport={'width': 1920, 'height': 1080}, device_scale_factor=1,
                                  record_video_dir=str(WORK / 'rec'), record_video_size={'width': 1920, 'height': 1080})
        ctx.add_init_script("try { localStorage.clear(); } catch (e) {}")
        pg = ctx.new_page(); t0 = time.monotonic()
        pg.add_init_script(RW.BRIDGE); pg.add_init_script(CURSOR)
        pg.add_init_script("document.addEventListener('DOMContentLoaded', () => { document.documentElement.style.zoom = '1.25'; });")
        pg.goto(f'http://127.0.0.1:{RW.PORT}/index.html')
        pg.wait_for_selector('.gcard', state='attached', timeout=60000)
        dwell = pg.wait_for_timeout; segs = {}; log = []
        now = lambda: round(time.monotonic() - t0, 3)
        def go(sel, click=True, steps=22):
            loc = pg.locator(sel).first
            try: loc.scroll_into_view_if_needed(timeout=4000)
            except Exception as e: log.append(f'not in view: {sel}'); return False
            box = loc.bounding_box()
            if not box: log.append('no box: ' + sel); return False
            pg.mouse.move(box['x'] + box['width'] / 2, box['y'] + box['height'] / 2, steps=steps); dwell(160)
            if click: pg.mouse.down(); dwell(70); pg.mouse.up()
            return True
        def scroll(sel, top): pg.evaluate(f"document.querySelector('{sel}').scrollTo({{top: {top}, behavior: 'smooth'}})")
        def seg(name, fn):
            segs[name] = [now()]
            try: fn()
            except Exception as e: log.append(f'{name}: {type(e).__name__}: {str(e)[:120]}')
            segs[name].append(now())
        pg.mouse.move(960, 540); dwell(900)

        def gallery():
            go('.railbtn[data-view="gallery"]'); dwell(900)
            go('#gallery-start .gcard >> nth=1', click=False); dwell(700)
            scroll('#gallery-scroll', 700); dwell(1700); scroll('#gallery-scroll', 1500); dwell(1500)
        seg('gallery', gallery); scroll('#gallery-scroll', 0); dwell(900)

        def theory():
            go('#gallery-start .gcard[aria-label^="Cylinder wake"]'); dwell(1500)
            pg.mouse.move(1400, 600, steps=14)
            scroll('#d-text', 420); dwell(1700); scroll('#d-text', 950); dwell(1700); scroll('#d-text', 1500); dwell(1500)
        seg('theory', theory); scroll('#d-text', 0); dwell(500)

        go('#d-open'); dwell(1600)
        names = pg.evaluate("[...document.querySelectorAll('#s-params .field')].map(f => f.dataset.name)")
        log.append('fields: ' + ', '.join(map(str, names)))
        def adjust():
            target = next((n for n in names if n and n.lower() in ('re', 'reynolds')), names[0] if names else None)
            if target and go(f'#s-params .field[data-name="{target}"] input'):
                pg.keyboard.press('Control+A'); dwell(250); pg.keyboard.type('150', delay=220); dwell(350); pg.keyboard.press('Tab'); dwell(900)
            if go('#s-derivedbox summary'): dwell(1900)
        seg('adjust', adjust)

        def run():
            go('#s-run'); pg.wait_for_selector('#s-views button', timeout=45000); dwell(2600)
        seg('run', run)

        def views():
            for v in ('Speed', 'Streamlines', 'Vorticity'):
                go(f'#s-views button:has-text("{v}")'); dwell(1250)
            pg.select_option('#s-cmap', 'Inferno'); dwell(1300); pg.select_option('#s-cmap', cached['defcmap']); dwell(500)
        seg('views', views)

        def plots():
            go('#s-plots'); dwell(2300); scroll('#s-plotpanel', 420); dwell(1700); scroll('#s-plotpanel', 900); dwell(1500)
        seg('plots', plots)

        def explain():
            go('#tab-explain'); dwell(2200); scroll('#s-help', 380); dwell(1600)
        seg('explain', explain); go('#tab-field'); dwell(600)

        def sweep():
            if go('#s-more'):
                dwell(700)
                if go('#s-moremenu button:has-text("Parameter sweep")'):
                    dwell(900)
                    if go('#s-sweep-values'): pg.keyboard.type('60, 120, 240', delay=110); dwell(1700)
        seg('sweep', sweep); dwell(400)

        video = pg.video; ctx.close(); browser.close()
        out = dict(video=str(video.path()) if video else None, segments=segs, log=log)
        (WORK / 'segments.json').write_text(json.dumps(out, indent=1)); print(json.dumps(out, indent=1))

if __name__ == '__main__':
    main()
