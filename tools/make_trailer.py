"""Funoos trailer: motion graphics over the gallery clips, with a synthesized soundtrack.

    python make_trailer.py [out.mp4]

Frames are composed with Pillow and piped to ffmpeg; the audio is generated with NumPy
(no samples, no licensed music). Cuts fall on a 100 BPM beat grid shared by picture and sound.
"""
import os, subprocess, sys, wave, shutil
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter
from scipy.signal import lfilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); GAL = os.path.join(ROOT, 'results', 'gallery')
UI = os.environ.get('FUNOOS_TRAILER_UI') or os.path.join(ROOT, 'results', '_trailer', 'ui')      # interface footage cut by cut_ui.py
OUT = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'funoos_trailer.mp4')
FFMPEG = shutil.which('ffmpeg')
W, H, FPS = 1920, 1080, 30
BEAT = 0.6; FB = int(BEAT * FPS)                    # 100 BPM, 18 frames per beat
BG = (8, 11, 20); ACC = (138, 162, 255); AMB = (255, 184, 107); TXT = (232, 238, 250); DIM = (140, 154, 180)
BOLD, MED, REG = 'Roboto:bold', 'Roboto:medium', 'Roboto'

CHAPTERS = [
    dict(name='EXTERNAL FLOW', method='lattice Boltzmann', beats=6, pairs=[
        (('lbm_cylinder', 'Cylinder wake', 'vortex shedding at Reynolds number 180', (0.04, 0.74)),
         ('lbm_airfoil', 'Airfoil at +14° incidence', 'lift from the pressure field', (0.04, 0.74))),
        (('lbm_f1', 'Car silhouette', 'wake and underbody', (0.02, 0.72)),
         ('lbm_peloton', 'Two riders drafting', 'the second rider sits in the wake', (0.0, 0.70))),
        (('lbm_name', 'Flow around text', 'any shape you type', (0.0, 0.70)),
         ('lbm_cyclist', 'A single rider', 'a body in the stream', (0.0, 0.70)))]),
    dict(name='BUOYANCY & CONVECTION', method='Navier–Stokes · projection', beats=6, pairs=[
        (('ns_rb_vigorous', 'Rayleigh–Bénard convection', 'a layer heated from below'),
         ('ns_chimney_strong', 'Plume in a crosswind', 'buoyancy against wind')),
        (('ns_smoke', 'Rising smoke', 'a buoyant plume'),
         ('ns_rt', 'Rayleigh–Taylor instability', 'heavy fluid over light'))]),
    dict(name='SHOCKS', method='compressible Euler', beats=3, shots=[
        ('euler_blast', 'Open-air blast', 'a pressure release'),
        ('euler_twin', 'Shock–bubble interaction', 'twin bubbles'),
        ('euler_city', 'Blast and obstacles', 'reflection and shielding')]),
    dict(name='FREE SURFACES', method='smoothed-particle hydrodynamics', beats=6, pairs=[
        (('sph_dam', 'Dam break', 'a column of water released'),
         ('sph_pour', 'Pouring', 'a jet filling a tank')),
        (('sph_ship', 'Floating hull in waves', 'a body carried by the water'),
         ('sph_slosh', 'Sloshing tank', 'a tank shaken sideways'))]),
    dict(name='PATTERNS & MIXING', method='spectral · reaction–diffusion · transport', beats=3, shots=[
        ('spec_kh', 'Kelvin–Helmholtz instability', 'a shear layer rolls up'),
        ('rd_maze', 'Gray–Scott patterns', 'reaction and diffusion'),
        ('mix_stir', 'Dye stirring', 'stretching and folding'),
        ('tracer_pulse', 'Tracer through porous rock', 'advection and dispersion')]),
    dict(name='INSIDE THE APP', method='read the theory · adjust · run · measure', beats=7, shots=[
        ('ui_gallery', 'Pick an experiment', '28 experiments, organised by phenomenon', (0.03, 0.0, 1.0, 0.86)),
        ('ui_theory', 'Read the theory', 'the physics, the model, the method and its limits', (0.0, 0.0, 1.0, 0.80)),
        ('ui_adjust', 'Adjust the setup', 'typed controls with units, ranges and derived quantities', (0.0, 0.0, 0.52, 0.50)),
        ('ui_run', 'Run it', 'the solver runs on your own machine', (0.0, 0.14, 1.0, 1.0)),
        ('ui_views', 'Switch views and palettes', 'vorticity, speed, streamlines', (0.30, 0.0, 1.0, 0.70)),
        ('ui_plots', 'Measure and plot', 'diagnostics with definitions and units', (0.28, 0.0, 1.0, 0.72)),
        ('ui_sweep', 'Sweep a parameter', 'queue runs and compare them', (0.0, 0.0, 0.56, 0.52))]),
]
# fraction of each clip's duration to show (default: skip the first 12 %)
# interface clips: the slice of each recording to show, and how many beats to give it, chosen so each action
# plays at about real speed and lasts as long as it needs
WIN = {'ui_gallery': (0.20, 0.90), 'ui_theory': (0.28, 0.95), 'ui_adjust': (0.30, 0.62), 'ui_run': (0.42, 0.95),
       'ui_views': (0.16, 0.42), 'ui_plots': (0.15, 0.70), 'ui_sweep': (0.80, 1.0),
       'sph_dam': (0.02, 0.55), 'sph_pour': (0.10, 0.80), 'euler_blast': (0.06, 0.75), 'euler_city': (0.20, 1.0),
       'ns_rt': (0.30, 1.0), 'ns_smoke': (0.25, 1.0), 'spec_kh': (0.25, 1.0), 'ns_chimney_strong': (0.10, 0.60),
       'rd_maze': (0.05, 0.85), 'tracer_pulse': (0.05, 0.9)}
START = {'ns_rb_vigorous': 0.12, 'ns_chimney_strong': 0.06, 'ns_smoke': 0.14, 'ns_rt': 0.15, 'sph_dam': 0.0,
         'sph_pour': 0.08, 'sph_ship': 0.10, 'sph_slosh': 0.10}
UIBEATS = {'ui_gallery': 9, 'ui_theory': 10, 'ui_adjust': 8, 'ui_run': 10, 'ui_views': 10, 'ui_plots': 10, 'ui_sweep': 8}
STATS = [(28, 'experiments'), (51, 'presets'), (5, 'solvers written from scratch'), (107, 'automated checks')]
MOS = ['lbm_cylinder', 'ns_rb_vigorous', 'euler_blast', 'sph_dam', 'rd_maze', 'spec_kh',
       'lbm_airfoil', 'ns_smoke', 'euler_twin', 'sph_pour', 'mix_stir', 'tracer_pulse']
INTRO_B, TITLE_B, STATS_B, OUTRO_B, TR = 6, 2, 8, 8, 7


def clamp(p): return max(0.0, min(1.0, p))
def ease(p): p = clamp(p); return 1 - (1 - p) ** 3
def col(c, a): return (c[0], c[1], c[2], int(255 * clamp(a)))

_fonts = {}
def F(style, size):
    if (style, size) not in _fonts:
        f = subprocess.run(['fc-match', '-f', '%{file}', style], capture_output=True, text=True).stdout.strip()
        _fonts[(style, size)] = ImageFont.truetype(f, size)
    return _fonts[(style, size)]

def text_w(s, font, tr=0): return sum(font.getlength(c) for c in s) + tr * (len(s) - 1)

def draw_text(d, x, y, s, font, fill, tr=0, anchor='l'):
    w = text_w(s, font, tr) if (tr or anchor != 'l') else 0
    if anchor == 'm': x -= w / 2
    elif anchor == 'r': x -= w
    if not tr:
        d.text((x, y), s, font=font, fill=fill); return
    for c in s:
        d.text((x, y), c, font=font, fill=fill); x += font.getlength(c) + tr

_clips = {}
def clip(key):
    if key not in _clips:
        p = f'{UI}/{key}.mp4' if key.startswith('ui_') else f'{GAL}/{key}.mp4'
        w, h = map(int, subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height',
                                        '-of', 'csv=p=0', p], capture_output=True, text=True).stdout.strip().split(','))
        raw = subprocess.run([FFMPEG, '-v', 'error', '-i', p, '-vf', 'fps=30', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'],
                             capture_output=True).stdout
        arr = np.frombuffer(raw, np.uint8).reshape(-1, h, w, 3)
        # the renderer puts the colour legend in a panel max(104, 16 % of the field width) wide on
        # the right (flowzoo/render.py: add_colorbar); recover the field width and drop the panel
        for fw in (() if key.startswith('ui_') else range(w - 104, w // 2, -1)):
            if abs(fw + max(104, int(fw * 0.16)) - w) <= 1:
                arr = arr[:, :, :fw - 1]; break
        _clips[key] = arr
    return _clips[key]

_BGA = np.array(BG, np.float32)
def bgfill(fr, strength=0.32):
    im = Image.fromarray(fr).resize((96, 54), Image.BILINEAR).filter(ImageFilter.GaussianBlur(5)).resize((W, H), Image.BICUBIC)
    return Image.fromarray((np.asarray(im, np.float32) * strength + _BGA * (1 - strength)).astype(np.uint8))

_masks, _shadows = {}, {}
def rmask(w, h, r=16):
    if (w, h) not in _masks:
        m = Image.new('L', (w, h), 0); ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255); _masks[(w, h)] = m
    return _masks[(w, h)]
def shadow(w, h):
    if (w, h) not in _shadows:
        s = Image.new('L', (w + 120, h + 120), 0); ImageDraw.Draw(s).rounded_rectangle((60, 74, 60 + w, 74 + h), 18, fill=170)
        _shadows[(w, h)] = s.filter(ImageFilter.GaussianBlur(26))
    return _shadows[(w, h)]

def place(base, fr, rect, zoom=1.0, dx=0):
    x0, y0, x1, y1 = rect; sw, sh = x1 - x0, y1 - y0; h, w = fr.shape[:2]
    sc = min(sw / w, sh / h); tw, th = int(w * sc) // 2 * 2, int(h * sc) // 2 * 2
    im = Image.fromarray(fr)
    if zoom > 1.0:
        cw, ch = int(w / zoom), int(h / zoom); im = im.crop(((w - cw) // 2, (h - ch) // 2, (w - cw) // 2 + cw, (h - ch) // 2 + ch))
    im = im.resize((tw, th), Image.LANCZOS)
    px, py = x0 + (sw - tw) // 2 + dx, y0 + (sh - th) // 2
    base.paste((0, 0, 0), (px - 60, py - 60), shadow(tw, th))
    base.paste(im, (px, py), rmask(tw, th))
    ImageDraw.Draw(base).rounded_rectangle((px, py, px + tw - 1, py + th - 1), 16, outline=(64, 78, 112), width=2)

def overlay(): return Image.new('RGBA', (W, H), (0, 0, 0, 0))

def hud(d, chapter, gp, method=None):
    draw_text(d, 96, 52, chapter, F(MED, 24), col(DIM, 1), tr=4)
    if method:
        x = 96 + text_w(chapter, F(MED, 24), 4) + 22
        draw_text(d, x, 52, '·   ' + method, F(MED, 24), col(ACC, 0.95), tr=1)
    draw_text(d, W - 96, 52, 'FUNOOS', F(BOLD, 24), col(ACC, 1), tr=6, anchor='r')
    d.rectangle((0, H - 4, int(W * gp), H), fill=col(ACC, 0.9))

def shot(f, nf, key, label, sub, method, chapter, gp, xwin=None, win=(0.12, 1.0)):
    c = clip(key); n = len(c); a, b = win
    fr = c[int((a + (b - a) * f / max(nf - 1, 1)) * (n - 1))]
    if xwin and len(xwin) == 2: fr = fr[:, int(xwin[0] * fr.shape[1]):int(xwin[1] * fr.shape[1])]
    elif xwin:                                              # a rectangle (x0, y0, x1, y1) in fractions of the frame
        hh_, ww_ = fr.shape[:2]; fr = fr[int(xwin[1] * hh_):int(xwin[3] * hh_), int(xwin[0] * ww_):int(xwin[2] * ww_)]
    base = bgfill(fr)
    place(base, fr, (96, 112, W - 96, H - 196), 1.0 if key.startswith('ui_') else 1 + 0.035 * f / nf, dx=int(150 * (1 - ease(f / 12))))
    ov = overlay(); d = ImageDraw.Draw(ov); hud(d, chapter, gp)
    y0 = H - 150
    hh = int(74 * ease(f / 9)); d.rectangle((96, y0 + 74 - hh, 103, y0 + 74), fill=col(AMB, 1))
    p = ease((f - 2) / 11); draw_text(d, 126 - 34 * (1 - p), y0 - 6, label, F(BOLD, 46), col(TXT, p))
    p2 = ease((f - 7) / 11)
    if sub: draw_text(d, 126, y0 + 48, sub, F(REG, 26), col(DIM, p2))
    if not key.startswith('ui_'):
        fw = text_w(method, F(MED, 24)); cx1 = W - 96; cx0 = cx1 - fw - 40
        d.rounded_rectangle((cx0, y0 + 14, cx1, y0 + 60), 23, outline=col(ACC, 0.85 * p2), width=2)
        draw_text(d, cx0 + 20, y0 + 22, method, F(MED, 24), col(ACC, p2))
    base.paste(ov, (0, 0), ov); return base

def pair(f, nf, items, method, chapter, gp):
    """Two examples side by side, each at its real speed: the clip starts where START says and is
    cut when the shot ends, never time-compressed."""
    frs = []
    for key, label, sub, *rest in items:
        c = clip(key); n = len(c); st = min(int(START.get(key, 0.03) * n), max(n - nf, 0))
        fr = c[min(st + f, n - 1)]
        if rest: fr = fr[:, int(rest[0][0] * fr.shape[1]):int(rest[0][1] * fr.shape[1])]
        frs.append(fr)
    th = Image.new('RGB', (96, 54))
    for i, fr in enumerate(frs): th.paste(Image.fromarray(fr).resize((48, 54), Image.BILINEAR), (48 * i, 0))
    th = th.filter(ImageFilter.GaussianBlur(6)).resize((W, H), Image.BICUBIC)
    base = Image.fromarray((np.asarray(th, np.float32) * 0.30 + _BGA * 0.70).astype(np.uint8))
    cw = (W - 192 - 28) // 2; cells = [(96, 112, 96 + cw, H - 196), (W - 96 - cw, 112, W - 96, H - 196)]
    for i, fr in enumerate(frs):
        place(base, fr, cells[i], 1 + 0.03 * f / nf, dx=int((-130 if i == 0 else 130) * (1 - ease((f - 3 * i) / 13))))
    ov = overlay(); d = ImageDraw.Draw(ov); hud(d, chapter, gp, method)
    y0 = H - 150
    for i, (key, label, sub, *rest) in enumerate(items):
        x = cells[i][0]; g = f - 4 * i
        hh = int(70 * ease(g / 9)); d.rectangle((x, y0 + 70 - hh, x + 6, y0 + 70), fill=col(AMB, 1))
        p = ease((g - 2) / 11); draw_text(d, x + 28 - 30 * (1 - p), y0 - 2, label, F(BOLD, 40), col(TXT, p))
        draw_text(d, x + 28, y0 + 44, sub, F(REG, 24), col(DIM, ease((g - 7) / 11)))
    base.paste(ov, (0, 0), ov); return base

def title(f, nf, ch, ci, total, gp):
    first = ch['pairs'][0][0][0] if 'pairs' in ch else ch['shots'][0][0]
    c = clip(first); base = bgfill(c[len(c) // 2], 0.20)
    ov = overlay(); d = ImageDraw.Draw(ov)
    name = ch['name']; size = 136
    while text_w(name, F(BOLD, size), 8) > 1560: size -= 6
    fnt = F(BOLD, size); tr = 8 + 64 * (1 - ease(f / 14)); a = ease(f / 8); y = H / 2 - 120 + 36 * (1 - ease(f / 12))
    draw_text(d, W / 2, y - 64, f'{ci:02d} / {total:02d}', F(MED, 30), col(AMB, ease((f - 2) / 8)), tr=6, anchor='m')
    draw_text(d, W / 2, y, name, fnt, col(TXT, a), tr=tr, anchor='m')
    bw = int(250 * ease((f - 6) / 14)); yb = int(y + size * 1.22)
    if bw > 0: d.rectangle((W / 2 - bw, yb, W / 2 + bw, yb + 5), fill=col(AMB, 1))
    draw_text(d, W / 2, yb + 34, ch['method'], F(REG, 34), col(DIM, ease((f - 12) / 10)), tr=2, anchor='m')
    d.rectangle((0, H - 4, int(W * gp), H), fill=col(ACC, 0.9))
    base.paste(ov, (0, 0), ov); return base

def glow_img(radius, color):
    yy, xx = np.mgrid[-radius:radius, -radius:radius]; r = np.sqrt(xx ** 2 + yy ** 2) / radius
    img = np.zeros((2 * radius, 2 * radius, 4), np.uint8); img[..., :3] = color
    img[..., 3] = (np.clip(1 - r, 0, 1) ** 2.2 * 255).astype(np.uint8); return Image.fromarray(img, 'RGBA')
GLOW = glow_img(700, AMB); _GA = np.asarray(GLOW.getchannel('A'), np.float32)

def paste_glow(base, k, cy):
    g = GLOW.copy(); g.putalpha(Image.fromarray((_GA * clamp(k)).astype(np.uint8)))
    base.paste(g, (W // 2 - 700, cy - 700), g)

def wordmark(d, f, y, size, start=10):
    fnt = F(BOLD, size); tr = 30; s = 'FUNOOS'; x = W / 2 - text_w(s, fnt, tr) / 2
    for i, ch in enumerate(s):
        p = ease((f - start - 4 * i) / 12)
        d.text((x, y + 44 * (1 - p)), ch, font=fnt, fill=col(TXT, p)); x += fnt.getlength(ch) + tr

def intro(f, nf):
    base = Image.new('RGB', (W, H), BG)
    paste_glow(base, 0.42 * ease(f / 45) * (1 + 0.06 * np.sin(f / 9)), H // 2 - 40)
    ov = overlay(); d = ImageDraw.Draw(ov)
    wordmark(d, f, H / 2 - 190, 210)
    lw = int(330 * ease((f - 38) / 20))
    if lw > 0: d.rectangle((W / 2 - lw, H / 2 + 78, W / 2 + lw, H / 2 + 82), fill=col(AMB, 1))
    draw_text(d, W / 2, H / 2 + 112, 'explore fluid motion through simulation', F(REG, 42), col(TXT, ease((f - 50) / 16)), tr=1, anchor='m')
    draw_text(d, W / 2, H / 2 + 180, 'an open-source desktop laboratory for computational fluid dynamics', F(REG, 26),
              col(DIM, ease((f - 64) / 16)), tr=1, anchor='m')
    base.paste(ov, (0, 0), ov)
    if f < 8: base = Image.blend(Image.new('RGB', (W, H), (0, 0, 0)), base, ease(f / 8))
    return base

def mosaic(f, strength=0.13):
    base = Image.new('RGB', (W, H), BG); cw, chh = W // 4, H // 3
    for i, k in enumerate(MOS):
        c = clip(k); im = Image.fromarray(c[(f * 2 + 17 * i) % len(c)]); w, h = im.size; sc = max(cw / w, chh / h)
        im = im.resize((int(w * sc) + 1, int(h * sc) + 1), Image.BILINEAR)
        x, y = (im.width - cw) // 2, (im.height - chh) // 2
        base.paste(im.crop((x, y, x + cw, y + chh)), ((i % 4) * cw, (i // 4) * chh))
    return Image.fromarray((np.asarray(base, np.float32) * strength + _BGA * (1 - strength)).astype(np.uint8))

def stats(f, nf, gp):
    base = mosaic(f); ov = overlay(); d = ImageDraw.Draw(ov)
    draw_text(d, W / 2, 150, 'ONE APP', F(MED, 30), col(AMB, ease(f / 10)), tr=10, anchor='m')
    for i, (val, lab) in enumerate(STATS):
        p = ease((f - 8 - 9 * i) / 30); x = W * (i + 0.5) / 4
        bw = int(46 * ease((f - 4 - 9 * i) / 12)); d.rectangle((x - bw, 372, x + bw, 377), fill=col(AMB, 1))
        draw_text(d, x, 400, str(int(round(val * p))), F(BOLD, 168), col(TXT, ease((f - 6 - 9 * i) / 10)), anchor='m')
        draw_text(d, x, 600, lab, F(REG, 30), col(DIM, ease((f - 16 - 9 * i) / 12)), tr=1, anchor='m')
    draw_text(d, W / 2, 800, 'set up  ·  run  ·  measure  ·  sweep  ·  compare  ·  reproduce', F(MED, 36), col(TXT, ease((f - 60) / 16)), tr=2, anchor='m')
    d.rectangle((0, H - 4, int(W * gp), H), fill=col(ACC, 0.9))
    base.paste(ov, (0, 0), ov); return base

def outro(f, nf):
    base = mosaic(f + 300, 0.10)
    paste_glow(base, 0.40 * ease(f / 30), H // 2 - 80)
    ov = overlay(); d = ImageDraw.Draw(ov)
    wordmark(d, f, H / 2 - 250, 180, start=4)
    draw_text(d, W / 2, H / 2 + 6, 'free and open source  ·  Windows  ·  macOS  ·  Linux', F(REG, 36), col(TXT, ease((f - 34) / 14)), tr=1, anchor='m')
    draw_text(d, W / 2, H / 2 + 96, 'github.com/SalehMohammadrezaei/Funoos', F(MED, 44), col(ACC, ease((f - 46) / 14)), tr=1, anchor='m')
    draw_text(d, W / 2, H / 2 + 190, 'made by Saleh Mohammadrezaei', F(REG, 28), col(DIM, ease((f - 58) / 14)), tr=2, anchor='m')
    base.paste(ov, (0, 0), ov)
    k = clamp((nf - f) / 24)
    return base if k >= 1 else Image.blend(Image.new('RGB', (W, H), (0, 0, 0)), base, k)


# ---- timeline: (kind, start beat, beats, payload) ----
SEG = [('intro', 0, INTRO_B, None)]; b = INTRO_B
for ci, ch in enumerate(CHAPTERS, 1):
    SEG.append(('title', b, TITLE_B, (ch, ci))); b += TITLE_B
    for s in ch.get('pairs', []):
        SEG.append(('pair', b, ch['beats'], (ch, s))); b += ch['beats']
    for s in ch.get('shots', []):
        nb = UIBEATS.get(s[0], ch['beats']); SEG.append(('shot', b, nb, (ch, s))); b += nb
SEG.append(('stats', b, STATS_B, None)); b += STATS_B
SEG.append(('outro', b, OUTRO_B, None)); b += OUTRO_B
TOTAL_B = b; NF = TOTAL_B * FB; DUR = TOTAL_B * BEAT


def audio(path):
    sr = 44100; n = int(DUR * sr); t = np.arange(n) / sr; rng = np.random.default_rng(7)
    L = np.zeros(n); R = np.zeros(n)
    hz = lambda m: 440.0 * 2 ** ((m - 69) / 12)
    LOOP = [[38, 45, 50, 53, 57, 64], [34, 41, 46, 50, 53, 57], [41, 48, 53, 57, 60, 67], [36, 43, 48, 52, 55, 62]]   # Dm9, Bbmaj7, Fadd9, Cadd9
    first, last = INTRO_B, TOTAL_B - OUTRO_B
    def chord_at(beat): return LOOP[0] if (beat < first or beat >= last) else LOOP[((beat - first) // 4) % 4]
    def lp(x, fc):
        a = np.exp(-2 * np.pi * fc / sr); return lfilter([1 - a], [1, -a], x)
    def add(sig, t0, pan=0.0, gain=1.0):
        i = int(t0 * sr)
        if i >= n: return
        if i < 0: sig = sig[-i:]; i = 0
        m = min(len(sig), n - i); l = np.sqrt(0.5 * (1 - pan)); r = np.sqrt(0.5 * (1 + pan))
        L[i:i + m] += sig[:m] * gain * l * 1.414; R[i:i + m] += sig[:m] * gain * r * 1.414
    # pad and bass: one chord per bar, cross-faded
    bars = [(0, first)] + [(bb, min(bb + 4, last)) for bb in range(first, last, 4)] + [(last, TOTAL_B)]
    for b0, b1 in bars:
        d = (b1 - b0) * BEAT + 0.9; m = int(d * sr); tt = np.arange(m) / sr
        env = np.clip(tt / 0.7, 0, 1) * np.clip((d - tt) / 0.9, 0, 1)
        pl = np.zeros(m); pr = np.zeros(m)
        for k, note in enumerate(chord_at(b0)):
            f0 = hz(note)
            for det, side in ((0.997, -1), (1.003, 1)):
                ph = 2 * np.pi * f0 * det * tt + k
                v = np.sin(ph) + 0.30 * np.sin(2 * ph) + 0.14 * np.sin(3 * ph)
                if side < 0: pl += v
                else: pr += v
        g = 0.030 if b0 >= first else 0.040
        i = int(b0 * BEAT * sr) - int(0.2 * sr); i0 = max(i, 0); cut = i0 - i; mm = min(m - cut, n - i0)
        L[i0:i0 + mm] += lp(pl * env, 1500)[cut:cut + mm] * g; R[i0:i0 + mm] += lp(pr * env, 1500)[cut:cut + mm] * g
        if b0 >= first:
            add(np.sin(2 * np.pi * hz(chord_at(b0)[0]) * tt) * env, b0 * BEAT - 0.2, 0.0, 0.16)
    # rhythm and arpeggio only during shots and the stats
    def pluck(f0, d=0.42):
        tt = np.arange(int(d * sr)) / sr; return (np.sin(2 * np.pi * f0 * tt) + 0.35 * np.sin(4 * np.pi * f0 * tt)) * np.exp(-tt / 0.13) * np.clip(tt / 0.004, 0, 1)
    tk = np.arange(int(0.30 * sr)) / sr
    kick = np.sin(2 * np.pi * (45 * tk + (120 - 45) * 0.045 * (1 - np.exp(-tk / 0.045)))) * np.exp(-tk / 0.15)
    th = np.arange(int(0.07 * sr)) / sr; hat_env = np.exp(-th / 0.018)
    tc = np.arange(int(0.22 * sr)) / sr
    step = 0
    for kind, b0, nb, pay in SEG:
        if kind not in ('shot', 'pair', 'stats'): continue
        for k in range(nb):
            beat = b0 + k; t0 = beat * BEAT; ch = chord_at(beat)
            if (beat - first) % 2 == 0: add(kick, t0, 0.0, 0.50)
            if (beat - first) % 4 == 2:
                nz = rng.standard_normal(len(tc)); add((nz - lp(nz, 900)) * np.exp(-tc / 0.07), t0, 0.1, 0.085)
            nz = rng.standard_normal(len(th)); add((nz - lp(nz, 6000)) * hat_env, t0 + BEAT / 2, rng.uniform(-0.5, 0.5), 0.045)
            for e in range(2):
                note = ch[2 + (step % 4)] + 12; pan = 0.55 if step % 2 else -0.55
                pk = pluck(hz(note)); add(pk, t0 + e * BEAT / 2, pan, 0.075)
                add(pk, t0 + e * BEAT / 2 + 0.30, -pan, 0.028); add(pk, t0 + e * BEAT / 2 + 0.60, pan, 0.012)
                step += 1
    # chapter hits: a rising whoosh into each title, then a low impact
    def whoosh(d=0.95):
        m = int(d * sr); tt = np.arange(m) / sr; nz = rng.standard_normal(m); r = tt / d
        return (lp(nz, 500) * (1 - r) * 2.2 + (nz - lp(nz, 2500)) * r * 0.9) * r ** 2
    tb = np.arange(int(1.4 * sr)) / sr
    boom = np.sin(2 * np.pi * (38 * tb + 30 * 0.12 * (1 - np.exp(-tb / 0.12)))) * np.exp(-tb / 0.42)
    for kind, b0, nb, pay in SEG:
        if kind in ('title', 'stats', 'outro'):
            t0 = b0 * BEAT; add(whoosh(), t0 - 0.95, 0.0, 0.13); add(boom, t0, 0.0, 0.50)
            nz = rng.standard_normal(int(0.5 * sr)); add(lp(nz, 1200) * np.exp(-np.arange(len(nz)) / sr / 0.12), t0, 0.0, 0.16)
    add(boom, 0.55, 0.0, 0.40)                                              # the wordmark lands
    tt = np.arange(int(2.4 * sr)) / sr                                      # shimmer under the intro and outro
    for t0 in (0.5, (TOTAL_B - OUTRO_B) * BEAT + 0.2):
        for k, note in enumerate((74, 77, 81, 86)):
            add(np.sin(2 * np.pi * hz(note) * tt) * np.exp(-tt / 0.9) * np.clip(tt / 0.02, 0, 1), t0 + 0.14 * k, (-1) ** k * 0.4, 0.035)
    mix = np.stack([L, R], 1)
    mix *= np.clip(t / 0.05, 0, 1)[:, None] * np.clip((DUR - t) / 2.2, 0, 1)[:, None]
    mix = np.tanh(1.25 * mix) / np.tanh(1.25); mix *= 0.89 / np.abs(mix).max()
    with wave.open(path, 'wb') as wv:
        wv.setnchannels(2); wv.setsampwidth(2); wv.setframerate(sr); wv.writeframes((mix * 32767).astype('<i2').tobytes())
    return float(np.abs(mix).max()), float(np.sqrt((mix ** 2).mean()))


def main():
    wav = OUT.replace('.mp4', '.wav'); pk, rms = audio(wav)
    print(f'audio: {DUR:.1f}s peak {pk:.2f} rms {rms:.3f}', flush=True)
    enc = subprocess.Popen([FFMPEG, '-y', '-v', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-',
                            '-i', wav, '-c:v', 'libx264', '-crf', '17', '-preset', 'medium', '-pix_fmt', 'yuv420p',
                            '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', '-shortest', OUT], stdin=subprocess.PIPE)
    prev = None; g = 0
    for kind, b0, nb, pay in SEG:
        nf = nb * FB
        for f in range(nf):
            gp = g / NF
            if kind == 'intro': im = intro(f, nf)
            elif kind == 'title': im = title(f, nf, pay[0], pay[1], len(CHAPTERS), gp)
            elif kind == 'pair': im = pair(f, nf, pay[1], pay[0]['method'], pay[0]['name'], gp)
            elif kind == 'shot': im = shot(f, nf, pay[1][0], pay[1][1], pay[1][2], pay[0]['method'], pay[0]['name'], gp,
                                           xwin=pay[1][3] if len(pay[1]) > 3 else None, win=WIN.get(pay[1][0], (0.12, 1.0)))
            elif kind == 'stats': im = stats(f, nf, gp)
            else: im = outro(f, nf)
            if prev is not None and f < TR:                                  # dissolve from the last frame, with a light sweep
                p = ease((f + 1) / (TR + 1)); im = Image.blend(prev, im, p)
                x = int(W * p); ImageDraw.Draw(im, 'RGBA').rectangle((x - 3, 0, x + 3, H), fill=col(AMB, 0.55 * (1 - p)))
            enc.stdin.write(im.tobytes()); g += 1
            last = im
        prev = last
        print(f'  {kind:6s} beat {b0:3d} done ({g}/{NF} frames)', flush=True)
    enc.stdin.close(); enc.wait()
    print('wrote', OUT, f'{os.path.getsize(OUT) / 1e6:.1f} MB')

if __name__ == '__main__':
    main()
