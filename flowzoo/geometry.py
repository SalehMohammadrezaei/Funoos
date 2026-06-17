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


def text(nx, ny, string, font_frac=0.55, font_path=None):
    """Render `string` as a solid obstacle centered in the domain.

    font_frac sets the glyph height as a fraction of the domain height.
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
    while font.getbbox(string)[2] > nx * 0.9 and size > 8:
        size -= 4
        font = ImageFont.truetype(path, size)
    bbox = draw.textbbox((0, 0), string, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.text(((nx - tw) / 2 - bbox[0], (ny - th) / 2 - bbox[1]), string,
              fill=255, font=font)
    arr = np.asarray(img)
    return (arr[::-1] > 127).astype(np.uint8)  # flip so text is upright in +y-up


def save_mask(mask, path):
    """Write the uint8 (Ny, Nx) mask as the flat binary the C++ solver reads."""
    mask.astype(np.uint8).tofile(path)
    return path
