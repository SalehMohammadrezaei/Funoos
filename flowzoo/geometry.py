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


def f1_car(nx, ny, cx, cy, length):
    """A Formula-1 car silhouette in side profile, nose into the wind (pointing −x).

    A bluff but streamlined body: tapered nose + front wing, a roll-hoop/airbox,
    a tall rear wing, and two wheels — the classic open-wheel aero shape.
    """
    img = Image.new("L", (nx, ny), 0); d = ImageDraw.Draw(img)
    L = float(length)
    def X(f): return cx + f * L
    def Y(f): return cy + f * L            # +Y is downward in PIL; flipped at the end → ground side
    d.polygon([(X(-0.50), Y(0.02)), (X(-0.40), Y(-0.04)), (X(0.30), Y(-0.05)),
               (X(0.46), Y(0.00)), (X(0.46), Y(0.10)), (X(-0.46), Y(0.10))], fill=255)   # body/floor
    d.polygon([(X(-0.50), Y(0.02)), (X(-0.30), Y(-0.02)), (X(-0.30), Y(0.07))], fill=255)  # nose cone
    d.rectangle([X(-0.56), Y(0.07), X(-0.42), Y(0.13)], fill=255)                          # front wing
    d.polygon([(X(-0.02), Y(-0.05)), (X(0.05), Y(-0.14)), (X(0.13), Y(-0.14)),
               (X(0.16), Y(-0.05))], fill=255)                                             # roll hoop / airbox
    d.rectangle([X(0.40), Y(-0.17), X(0.50), Y(-0.05)], fill=255)                          # rear wing post
    d.rectangle([X(0.34), Y(-0.18), X(0.54), Y(-0.12)], fill=255)                          # rear wing plane
    rw = 0.10 * L
    for fx in (-0.34, 0.30):                                                               # front & rear wheels
        d.ellipse([X(fx) - rw, Y(0.09) - rw, X(fx) + rw, Y(0.09) + rw], fill=255)
    arr = np.asarray(img)
    return (arr[::-1] > 127).astype(np.uint8)


def cyclist(nx, ny, cx, cy, size, riders=1, gap=1.05):
    """One or more cyclists in an aero tuck, facing the wind (−x).

    With riders=2 the second sits in the leader's slipstream — a drafting pair,
    so the sheltered low-speed pocket between them is visible.
    """
    img = Image.new("L", (nx, ny), 0); d = ImageDraw.Draw(img)
    S = float(size)
    rw = 0.17 * S; lw = max(2, int(0.05 * S))
    def draw_one(ox):
        def X(f): return cx + ox + f * S
        def Y(f): return cy + f * S
        for fx in (-0.34, 0.32):                                # two wheels (solid discs)
            d.ellipse([X(fx) - rw, Y(0.30) - rw, X(fx) + rw, Y(0.30) + rw], fill=255)
        d.line([X(-0.34), Y(0.30), X(-0.10), Y(0.30)], fill=255, width=lw)       # frame
        d.line([X(0.32), Y(0.30), X(-0.10), Y(0.30)], fill=255, width=lw)
        d.polygon([(X(0.10), Y(0.04)), (X(-0.22), Y(-0.10)), (X(-0.30), Y(-0.02)),
                   (X(-0.06), Y(0.30)), (X(0.16), Y(0.30))], fill=255)            # tuck: head/shoulders into wind (−x)
        hr = 0.12 * S
        d.ellipse([X(-0.28) - hr, Y(-0.16) - hr, X(-0.28) + hr, Y(-0.16) + hr], fill=255)  # head/helmet (forward, −x)
    total = riders
    start = -0.5 * (total - 1) * gap
    for k in range(total):
        draw_one((start + k * gap) * S)
    arr = np.asarray(img)
    return (arr[::-1] > 127).astype(np.uint8)


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
