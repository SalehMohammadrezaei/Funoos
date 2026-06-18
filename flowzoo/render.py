"""FlowZoo shared rendering pipeline — the gallery's visual identity.

Every exhibit renders through here so the whole zoo looks like one polished
product: a custom cinematic colormap, dark background, crisp upscaling, and
high-quality GIF + MP4 export.
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import matplotlib
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image


def _ffmpeg():
    """Locate ffmpeg: env override, bundled (PyInstaller), then PATH."""
    if os.environ.get("FLOWZOO_FFMPEG"):
        return os.environ["FLOWZOO_FFMPEG"]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        cand = Path(base) / exe
        if cand.exists():
            return str(cand)
    return "ffmpeg"

# --- FlowZoo signature colormaps ---------------------------------------------
# Diverging "curl" map for vorticity: cyan -> teal -> ink -> rust -> amber,
# dark-centered so structures glow on a near-black background.
FLOWZOO_CURL = LinearSegmentedColormap.from_list("flowzoo_curl", [
    (0.00, "#3fe0ff"), (0.25, "#1a6e8e"), (0.50, "#0a0b12"),
    (0.75, "#b3432a"), (1.00, "#ffb02c"),
])
# Sequential "ember" map for speed / density / scalars.
FLOWZOO_EMBER = LinearSegmentedColormap.from_list("flowzoo_ember", [
    (0.00, "#05060d"), (0.30, "#3b0f55"), (0.6, "#c43c4e"),
    (0.82, "#ff8c2b"), (1.00, "#ffe9a8"),
])
# Water map for SPH particles: deep blue -> cyan -> white foam at high speed.
FLOWZOO_WATER = LinearSegmentedColormap.from_list("flowzoo_water", [
    (0.00, "#0a1a3a"), (0.45, "#1f6fb2"), (0.78, "#56c5e8"), (1.00, "#eaffff"),
])
# Two-tone map for Rayleigh-Taylor: light fluid = cool teal, heavy = warm amber.
FLOWZOO_RT = LinearSegmentedColormap.from_list("flowzoo_rt", [
    (0.00, "#0e3d4d"), (0.35, "#2fb6c4"), (0.5, "#e9f6f4"),
    (0.65, "#f2a23c"), (1.00, "#7a1f12"),
])
INK = "#0a0b12"   # canonical background
SOLID = "#aab4c4"  # solid-phase color (obstacles: cylinder, letters)

# Curated palette set the GUI lets users pick from (FlowZoo customs + classics).
COLORMAPS = {
    "Curl (cyan–amber)": FLOWZOO_CURL,
    "Ember (fire)": FLOWZOO_EMBER,
    "Ocean (water)": FLOWZOO_WATER,
    "Hot / Cold": FLOWZOO_RT,
    "Inferno": "inferno",
    "Magma": "magma",
    "Plasma": "plasma",
    "Viridis": "viridis",
    "Twilight": "twilight_shifted",
    "Turbo": "turbo",
}


def _font(sz):
    from PIL import ImageFont
    for p in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
              "C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf"):
        try:
            return ImageFont.truetype(p, sz)
        except OSError:
            continue
    return ImageFont.load_default()


def add_colorbar(rgb, cmap, vmin, vmax, label=""):
    """Add a labelled colorbar in a panel to the RIGHT of the field (not over it)."""
    from PIL import ImageDraw
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    H, W = rgb.shape[:2]
    fs = max(11, H // 40); fnt = _font(fs)
    panel = max(104, int(W * 0.16))
    bgc = np.array(Image.new("RGB", (1, 1), "#0c0f1a"))[0, 0]
    canvas = np.empty((H, W + panel, 3), dtype=np.uint8)
    canvas[:, :W] = rgb; canvas[:, W:] = bgc
    img = Image.fromarray(canvas); d = ImageDraw.Draw(img)
    d.line([W, 0, W, H], fill=(40, 50, 80))                       # divider
    bw = max(14, panel // 6); bh = int(H * 0.6)
    x0 = W + 14; y0 = int(H * 0.18)
    for k in range(bh):
        c = cmap(1 - k / bh)
        d.line([x0, y0 + k, x0 + bw, y0 + k], fill=tuple(int(255 * v) for v in c[:3]))
    d.rectangle([x0, y0, x0 + bw, y0 + bh], outline=(210, 218, 230))
    for f in (0.0, 0.25, 0.5, 0.75, 1.0):
        val = vmin + (vmax - vmin) * f; yy = y0 + int((1 - f) * bh)
        d.line([x0 + bw, yy, x0 + bw + 4, yy], fill=(210, 218, 230))
        d.text((x0 + bw + 7, yy - fs // 2), f"{val:.2g}", fill=(228, 233, 243), font=fnt)
    if label:
        d.text((x0 - 2, y0 - fs - 7), label, fill=(228, 233, 243), font=fnt)
    return np.asarray(img)


def _spark_color(h):
    """Heat h in [0,1] → deep-red → orange → white-hot."""
    h = max(0.0, min(1.0, h))
    return (255, int(70 + 185 * h), int(20 + 210 * max(0.0, h - 0.5) * 2))


def overlay_particles(rgb, xs, ys, sizes, heat=None):
    """Draw glowing ember/spark debris (glow halo + bright core, hot palette)."""
    from PIL import ImageDraw
    img = Image.fromarray(rgb).convert("RGB")
    d = ImageDraw.Draw(img, "RGBA")
    if heat is None:
        heat = [1.0] * len(xs)
    for x, y, s, h in zip(xs, ys, sizes, heat):
        col = _spark_color(h)
        d.ellipse([x - 2.6 * s, y - 2.6 * s, x + 2.6 * s, y + 2.6 * s],
                  fill=(*col, 45))                                   # soft outer glow
        d.ellipse([x - 1.4 * s, y - 1.4 * s, x + 1.4 * s, y + 1.4 * s],
                  fill=(*col, 120))                                  # inner glow
        core = tuple(min(255, c + 55) for c in col)
        d.ellipse([x - 0.7 * s, y - 0.7 * s, x + 0.7 * s, y + 0.7 * s], fill=core)  # hot core
    return np.asarray(img)


def vorticity(ux, uy):
    """omega_z = d(uy)/dx - d(ux)/dy on a unit-spaced grid."""
    duy_dx = np.gradient(uy, axis=1)
    dux_dy = np.gradient(ux, axis=0)
    return duy_dx - dux_dy


def speed(ux, uy):
    return np.sqrt(ux * ux + uy * uy)


def schlieren(rho):
    """|grad rho| — the classic visualization that lights up shock fronts."""
    gy, gx = np.gradient(rho)
    return np.sqrt(gx * gx + gy * gy)


def field_to_rgb(field, cmap, vmin, vmax, mask=None, mask_color=INK,
                 upscale=2, gamma=1.0):
    """Map a scalar field to an RGB uint8 image with the FlowZoo look."""
    x = np.clip((field - vmin) / (vmax - vmin + 1e-30), 0, 1)
    if gamma != 1.0:
        x = x ** gamma
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    rgb = (cmap(x)[..., :3] * 255).astype(np.uint8)
    if mask is not None:
        mc = np.array(Image.new("RGB", (1, 1), mask_color))[0, 0]
        rgb[mask.astype(bool)] = mc
    img = Image.fromarray(rgb[::-1])  # flip so +y is up
    if upscale and upscale != 1:
        img = img.resize((img.width * upscale, img.height * upscale),
                         Image.BILINEAR)
    return np.asarray(img)


def _write_pngs(frames, d):
    for i, fr in enumerate(frames):
        Image.fromarray(fr).save(str(Path(d) / f"f_{i:05d}.png"))
    return str(Path(d) / "f_%05d.png")


_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def save_mp4(frames, path, fps=30):
    """Encode frames to H.264 MP4 using the system ffmpeg."""
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        inp = _write_pngs(frames, d)
        subprocess.run([_ffmpeg(), "-y", "-v", "error", "-framerate", str(fps),
                        "-i", inp, "-vf", _EVEN, "-pix_fmt", "yuv420p",
                        "-c:v", "libx264", "-crf", "18", path], check=True)
    return path


def save_gif(frames, path, fps=30):
    """High-quality GIF via ffmpeg two-pass palettegen/paletteuse."""
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as d:
        inp = _write_pngs(frames, d)
        pal = str(Path(d) / "pal.png")
        vf = f"fps={fps},{_EVEN}:flags=lanczos"
        subprocess.run([_ffmpeg(), "-y", "-v", "error", "-framerate", str(fps),
                        "-i", inp, "-vf", vf + ",palettegen=stats_mode=diff",
                        pal], check=True)
        subprocess.run([_ffmpeg(), "-y", "-v", "error", "-framerate", str(fps),
                        "-i", inp, "-i", pal, "-lavfi",
                        vf + "[x];[x][1:v]paletteuse=dither=sierra2_4a",
                        "-loop", "0", path], check=True)
    return path


def symmetric_limit(field, pct=99.5):
    """A robust symmetric color limit for diverging fields (vorticity)."""
    v = np.percentile(np.abs(field), pct)
    return -v, v


def streamlines_rgb(ux, uy, cmap=FLOWZOO_EMBER, mask=None, mask_color=SOLID,
                    density=1.1, bg=INK, dpi=100, vmax=None):
    """Render flow streamlines colored by speed to an RGB frame."""
    import matplotlib.pyplot as plt
    ny, nx = ux.shape
    spd = np.sqrt(ux * ux + uy * uy)
    u, v = ux.copy(), uy.copy()
    if mask is not None:
        m = mask.astype(bool); u[m] = 0; v[m] = 0
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    fig = plt.figure(figsize=(nx / dpi, ny / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(bg); fig.patch.set_facecolor(bg)
    Y, X = np.mgrid[0:ny, 0:nx]
    if vmax is None:
        vmax = np.percentile(spd, 99.5) + 1e-12
    lw = 0.6 + 1.1 * np.clip(spd / vmax, 0, 1)
    try:
        ax.streamplot(X, Y, u, v, color=spd, cmap=cmap, density=density,
                      linewidth=lw, arrowsize=0.7, norm=plt.Normalize(0, vmax))
    except Exception:
        ax.streamplot(X, Y, u, v, color="#7fd0ff", density=density, linewidth=1.0)
    if mask is not None:
        from PIL import Image as _I
        mc = np.array(_I.new("RGB", (1, 1), mask_color))[0, 0] / 255.0
        ov = np.zeros((ny, nx, 4)); ov[m] = [*mc, 1.0]
        ax.imshow(ov, origin="lower", extent=[0, nx, 0, ny], zorder=5)
    ax.set_xlim(0, nx - 1); ax.set_ylim(0, ny - 1); ax.axis("off")
    fig.canvas.draw(); w, h = fig.canvas.get_width_height()
    rgb = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h, w, 4)[..., :3].copy()
    plt.close(fig)
    return rgb
