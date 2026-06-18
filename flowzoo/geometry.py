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


def save_mask(mask, path):
    """Write the uint8 (Ny, Nx) mask as the flat binary the C++ solver reads."""
    mask.astype(np.uint8).tofile(path)
    return path
