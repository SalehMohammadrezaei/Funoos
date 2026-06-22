"""Obstacle geometries for the LBM exhibits.

Masks use the solver convention: uint8 array (Ny, Nx), 1 = solid. Each helper
can write the mask to the flat binary file the C++ solver reads.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
]


def cylinder(nx, ny, cx, cy, radius):
    """Single circular obstacle."""
    yy, xx = np.mgrid[0:ny, 0:nx]
    return ((xx - cx) ** 2 + (yy - cy) ** 2 <= radius * radius).astype(np.uint8)


def square(nx, ny, cx, cy, half):
    """Axis-aligned square bluff body."""
    yy, xx = np.mgrid[0:ny, 0:nx]
    return ((np.abs(xx - cx) <= half) & (np.abs(yy - cy) <= half)).astype(np.uint8)


def diamond(nx, ny, cx, cy, half):
    """Square rotated 45° (a sharp-nosed bluff body)."""
    yy, xx = np.mgrid[0:ny, 0:nx]
    return ((np.abs(xx - cx) + np.abs(yy - cy)) <= half).astype(np.uint8)


def airfoil(nx, ny, cx, cy, chord, thickness=0.12, aoa_deg=12.0):
    """NACA-symmetric airfoil at angle of attack (lifting body with a clean wake)."""
    yy, xx = np.mgrid[0:ny, 0:nx]
    a = np.deg2rad(aoa_deg); ca, sa = np.cos(a), np.sin(a)
    X = (xx - cx) * ca - (yy - cy) * sa + 0.35 * chord     # leading edge near front
    Y = (xx - cx) * sa + (yy - cy) * ca
    t = np.clip(X / chord, 0, 1)
    yt = 5 * thickness * chord * (0.2969 * np.sqrt(t) - 0.126 * t - 0.3516 * t ** 2
                                  + 0.2843 * t ** 3 - 0.1015 * t ** 4)
    return ((X >= 0) & (X <= chord) & (np.abs(Y) <= yt)).astype(np.uint8)


def text(nx, ny, string, font_frac=0.55, x_frac=0.5, max_w_frac=0.9,
         font_path=None):
    """Render `string` as a solid obstacle in the domain.

    font_frac sets the glyph height as a fraction of the domain height;
    x_frac sets where the text block is centered horizontally (0..1), so the
    wake can trail downstream; max_w_frac caps the text width.
    """
    img = Image.new("L", (nx, ny), 0)
    draw = ImageDraw.Draw(img)
    target_h = int(ny * font_frac)
    path = font_path
    if path is None:
        for c in _FONT_CANDIDATES:
            try:
                ImageFont.truetype(c, 10); path = c; break
            except OSError:
                continue
    size = target_h
    font = ImageFont.truetype(path, size)
    # shrink to fit width
    while font.getbbox(string)[2] > nx * max_w_frac and size > 8:
        size -= 4
        font = ImageFont.truetype(path, size)
    bbox = draw.textbbox((0, 0), string, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    margin = 0.03 * nx
    left = x_frac * nx - tw / 2                       # desired left edge
    left = min(max(left, margin), nx - margin - tw)  # clamp fully on-screen
    draw.text((left - bbox[0], (ny - th) / 2 - bbox[1]), string,
              fill=255, font=font)
    arr = np.asarray(img)
    return (arr[::-1] > 127).astype(np.uint8)  # flip so text is upright in +y-up


def f1_car(nx, ny, cx, length, clearance=4):
    """A realistic modern Formula-1 side profile sitting on the ground, nose into the wind (−x).

    Traced from the real shape: front wing + endplate, a raised nose tapering up to the
    chassis, cockpit with the halo hoop and helmet, the airbox peak, a coke-bottle engine
    cover, a rear wing on its pylon with endplate, the diffuser, and two open wheels that
    poke above the low body.
    """
    img = Image.new("L", (nx, ny), 0); d = ImageDraw.Draw(img)
    L = float(length); B = ny - 1 - clearance         # ground line; v = height above it
    def P(u, v): return (cx + u * L, B - v * L)
    def box(u0, v0, u1, v1):
        x0, y0 = P(u0, v0); x1, y1 = P(u1, v1)
        d.rectangle([min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)], fill=255)
    top = [(-0.50, 0.05), (-0.50, 0.092), (-0.45, 0.10), (-0.43, 0.108),
           (-0.40, 0.125), (-0.34, 0.15), (-0.24, 0.168), (-0.14, 0.178), (-0.085, 0.18),
           (-0.05, 0.182), (-0.032, 0.20), (-0.012, 0.232), (0.005, 0.243), (0.022, 0.232), (0.038, 0.196),
           (0.052, 0.188), (0.075, 0.214), (0.094, 0.243), (0.115, 0.226),
           (0.20, 0.196), (0.30, 0.168), (0.375, 0.150), (0.405, 0.165),
           (0.405, 0.262), (0.45, 0.272), (0.53, 0.272), (0.532, 0.262),
           (0.532, 0.232), (0.452, 0.228), (0.45, 0.196), (0.43, 0.182),
           (0.47, 0.14), (0.522, 0.122), (0.522, 0.06)]
    bot = [(0.42, 0.05), (0.30, 0.044), (-0.36, 0.044), (-0.42, 0.048)]
    d.polygon([P(u, v) for u, v in top + bot], fill=255)
    box(-0.525, 0.04, -0.50, 0.118)                    # front-wing endplate
    box(0.518, 0.118, 0.542, 0.262)                    # rear-wing endplate
    for u, r in [(-0.30, 0.118), (0.315, 0.122)]:      # open wheels (poke above the low body)
        x0, y0 = P(u, r); rr = r * L; d.ellipse([x0 - rr, y0 - rr, x0 + rr, y0 + rr], fill=255)
    return (np.asarray(img)[::-1] > 127).astype(np.uint8)


def cyclist(nx, ny, cx, size, riders=1, gap=1.05, clearance=4):
    """A realistic road cyclist on a drop-bar bike, sitting on the road, facing the wind (−x).

    Spoked wheels, a double-triangle frame with fork and drop handlebars, and a rider in an
    aero road position (flat back, arms to the drops, aero helmet, leg bent to the cranks).
    With riders=2 the second sits in the leader's slipstream — a drafting pair, so the
    sheltered low-speed pocket behind the leader is visible.
    """
    img = Image.new("L", (nx, ny), 0); d = ImageDraw.Draw(img)
    S = float(size); B = ny - 1 - clearance
    rW = 0.30; lw = max(2, int(0.05 * S))
    def draw_one(ox):
        def P(u, v): return (cx + ox + u * S, B - v * S)
        for u in (-0.46, 0.46):                        # spoked wheels (rim rings)
            x0, y0 = P(u, rW); rr = rW * S; d.ellipse([x0 - rr, y0 - rr, x0 + rr, y0 + rr], outline=255, width=max(3, int(0.07 * S)))
        bb, rh, fh, st, ht = P(0.02, 0.26), P(0.46, 0.30), P(-0.46, 0.30), P(0.20, 0.62), P(-0.30, 0.60)
        for a, b in [(bb, rh), (bb, st), (st, rh), (st, ht), (bb, ht), (ht, fh)]:   # diamond frame + fork
            d.line([a, b], fill=255, width=lw)
        hb = P(-0.40, 0.585)
        d.line([ht, hb], fill=255, width=lw); d.line([hb, P(-0.44, 0.55)], fill=255, width=lw)  # drop bars
        hip, sho, hand = P(0.17, 0.64), P(-0.20, 0.72), P(-0.42, 0.57)
        d.line([hip, sho], fill=255, width=int(lw * 2.6))                          # flat back / torso
        d.line([sho, hand], fill=255, width=int(lw * 1.3))                         # arm to the drops
        knee = P(0.0, 0.42)
        d.line([hip, knee], fill=255, width=int(lw * 1.8)); d.line([knee, bb], fill=255, width=int(lw * 1.5))  # leg
        hr = 0.10 * S; hx, hy = P(-0.30, 0.74)
        d.ellipse([hx - hr * 1.5, hy - hr, hx + hr, hy + hr], fill=255)            # aero teardrop helmet (−x)
    start = -0.5 * (riders - 1) * gap
    for k in range(riders):
        draw_one((start + k * gap) * S)
    return (np.asarray(img)[::-1] > 127).astype(np.uint8)


def porous(nx, ny, solid_frac=0.4, grain=12, seed=0):
    """Random grain pack (periodic) filling to a target solid fraction — a porous sample."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:ny, 0:nx]
    mask = np.zeros((ny, nx), np.uint8)
    tries = 0
    while mask.mean() < solid_frac and tries < 8000:
        cx, cy = rng.integers(0, nx), rng.integers(0, ny)
        r = grain * rng.uniform(0.6, 1.4)
        dx = np.minimum(np.abs(xx - cx), nx - np.abs(xx - cx))   # periodic distance
        dy = np.minimum(np.abs(yy - cy), ny - np.abs(yy - cy))
        mask |= (dx * dx + dy * dy <= r * r).astype(np.uint8)
        tries += 1
    return mask


def save_mask(mask, path):
    """Write the uint8 (Ny, Nx) mask as the flat binary the C++ solver reads."""
    mask.astype(np.uint8).tofile(path)
    return path
