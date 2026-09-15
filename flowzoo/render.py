"""Funoos shared rendering pipeline — the gallery's visual identity.

Every exhibit renders through here so the whole zoo looks like one polished
product: a custom cinematic colormap, dark background, crisp upscaling, and
high-quality GIF + MP4 export.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

import numpy as np
import matplotlib
from matplotlib.colors import LinearSegmentedColormap
from PIL import Image


def _ffmpeg():
    """Locate ffmpeg: env override, bundled (PyInstaller), imageio-ffmpeg, then PATH."""
    if os.environ.get("FLOWZOO_FFMPEG"):
        return os.environ["FLOWZOO_FFMPEG"]
    base = getattr(sys, "_MEIPASS", None)
    if base:
        exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
        cand = Path(base) / exe
        if cand.exists():
            return str(cand)
    # pip-installable ffmpeg binary (no separate install needed): pip install imageio-ffmpeg
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        pass
    import shutil
    return shutil.which("ffmpeg") or "ffmpeg"

# --- Funoos signature colormaps ---------------------------------------------
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
# Cool monochrome smoke: dark navy -> slate -> ash white (distinct from the warm flame).
FLOWZOO_SMOKE = LinearSegmentedColormap.from_list("flowzoo_smoke", [
    (0.00, "#0a0f1e"), (0.40, "#3a4a64"), (0.75, "#8b97ad"), (1.00, "#eef2f8"),
])
INK = "#0a0b12"   # canonical background
SOLID = "#aab4c4"  # solid-phase color (obstacles: cylinder, letters)

# Curated palette set the GUI lets users pick from (Funoos customs + classics).
COLORMAPS = {
    "Curl (cyan–amber)": FLOWZOO_CURL,
    "Ember (fire)": FLOWZOO_EMBER,
    "Smoke (mono)": FLOWZOO_SMOKE,
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


class Norm:
    """One colour normalisation shared by the field image and its colourbar.

    value -> t = clip((v - vmin)/(vmax - vmin), 0, 1) ** gamma -> colormap(t).
    `gamma` < 1 brightens low values (used for faint scalars); the colourbar
    inverts the same transform for its tick values, so the legend always shows
    the colour a given value actually gets. `clipped(field)` reports the fraction
    of samples outside [vmin, vmax] (saturated) so the UI can flag clipping.
    Changing the palette never changes the numbers: the palette is applied after
    this mapping.
    """

    def __init__(self, vmin, vmax, gamma=1.0, floor=0.0):
        self.vmin, self.vmax, self.gamma = float(vmin), float(vmax), float(gamma)
        self.floor = float(floor)          # lowest colour position used (e.g. resting water stays visible)

    def __call__(self, field):
        t = np.clip((np.asarray(field, dtype=np.float64) - self.vmin) / (self.vmax - self.vmin + 1e-30), 0, 1)
        t = t ** self.gamma if self.gamma != 1.0 else t
        return self.floor + (1.0 - self.floor) * t if self.floor else t

    def inverse(self, t):
        """Value whose colour sits at colourbar position t in [0, 1] (positions below
        `floor` map to vmin)."""
        t = np.asarray(t, dtype=np.float64)
        if self.floor:
            t = np.clip((t - self.floor) / (1.0 - self.floor), 0, 1)
        return self.vmin + (self.vmax - self.vmin) * (t ** (1.0 / self.gamma) if self.gamma != 1.0 else t)

    def with_range(self, vmin=None, vmax=None):
        """Copy with manual colour limits (None keeps the automatic value)."""
        return Norm(self.vmin if vmin is None else vmin, self.vmax if vmax is None else vmax,
                    self.gamma, self.floor)

    def clipped(self, field):
        f = np.asarray(field); f = f[np.isfinite(f)]
        if f.size == 0:
            return 0.0
        return float(np.mean((f < self.vmin) | (f > self.vmax)))

    @property
    def diverging(self):
        return self.vmin < 0 < self.vmax and abs(self.vmin + self.vmax) < 1e-9 * (abs(self.vmax) + 1e-30)


def add_colorbar(rgb, cmap, vmin, vmax=None, label="", gamma=1.0, clip_frac=None):
    """Add a labelled colourbar in a panel to the RIGHT of the field (not over it).

    `vmin` may be a `Norm` (then vmax/gamma are taken from it). Tick values are
    read back through the same normalisation used for the image, so a gamma-
    brightened field and its legend agree. If `clip_frac` (fraction of samples
    outside the colour range) is above 0.5 % the bar is annotated as clipped.
    """
    from PIL import ImageDraw
    norm = vmin if isinstance(vmin, Norm) else Norm(vmin, vmax, gamma)
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
        val = float(norm.inverse(f)); yy = y0 + int((1 - f) * bh)
        d.line([x0 + bw, yy, x0 + bw + 4, yy], fill=(210, 218, 230))
        d.text((x0 + bw + 7, yy - fs // 2), f"{val:.2g}", fill=(228, 233, 243), font=fnt)
    if norm.diverging:                                            # mark the zero of a signed field
        yz = y0 + int((1 - float(norm(0.0))) * bh)
        d.line([x0 - 4, yz, x0, yz], fill=(228, 233, 243))
    if label:
        d.text((x0 - 2, y0 - fs - 7), label, fill=(228, 233, 243), font=fnt)
    if clip_frac is not None and clip_frac > 0.005:
        d.text((x0 - 2, y0 + bh + 8), f"▲ {100 * clip_frac:.0f}% clipped", fill=(255, 176, 44), font=fnt)
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


def vorticity(ux, uy, dx=1.0):
    """omega_z = d(uy)/dx - d(ux)/dy. Arrays are [y, x]; `dx` is the grid spacing
    (1 lattice unit unless the caller supplies the physical spacing)."""
    duy_dx = np.gradient(uy, dx, axis=1)
    dux_dy = np.gradient(ux, dx, axis=0)
    return duy_dx - dux_dy


def speed(ux, uy):
    return np.sqrt(ux * ux + uy * uy)


def schlieren(rho):
    """|grad rho| — the classic visualization that lights up shock fronts."""
    gy, gx = np.gradient(rho)
    return np.sqrt(gx * gx + gy * gy)


def field_to_rgb(field, cmap, vmin, vmax=None, mask=None, mask_color=INK,
                 upscale=2, gamma=1.0, empty=None, empty_color="#141a2b"):
    """Map a scalar field to an RGB uint8 image with the Funoos look.

    `vmin` may be a `Norm`. `mask` marks solid cells (painted `mask_color`);
    `empty` marks cells with no fluid at all (painted `empty_color`, distinct
    from fluid at zero — e.g. air above an SPH free surface). NaN in `field` is
    treated as empty.
    """
    norm = vmin if isinstance(vmin, Norm) else Norm(vmin, vmax, gamma)
    fld = np.asarray(field, dtype=np.float64)
    nan = ~np.isfinite(fld)
    x = norm(np.where(nan, norm.vmin, fld))
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    rgb = (cmap(x)[..., :3] * 255).astype(np.uint8)
    if empty is not None or nan.any():
        e = nan if empty is None else (np.asarray(empty, dtype=bool) | nan)
        ec = np.array(Image.new("RGB", (1, 1), empty_color))[0, 0]
        rgb[e] = ec
    if mask is not None:
        mc = np.array(Image.new("RGB", (1, 1), mask_color))[0, 0]
        rgb[np.asarray(mask).astype(bool)] = mc
    img = Image.fromarray(rgb[::-1])  # flip so +y is up
    if upscale and upscale != 1:
        img = img.resize((img.width * upscale, img.height * upscale),
                         Image.BILINEAR)
    return np.asarray(img)


_EVEN = "scale=trunc(iw/2)*2:trunc(ih/2)*2"


def _pipe_frames(cmd, frames):
    """Feed uint8 RGB frames to ffmpeg over a raw-video pipe (no intermediate PNGs).

    `frames` is any iterable of HxWx3 uint8 arrays with identical shapes; a
    generator lets a caller stream frames without materialising them all.
    Returns the number of frames written.
    """
    it = iter(frames)
    try:
        first = next(it)
    except StopIteration:
        raise ValueError("no frames to encode")
    first = np.ascontiguousarray(first, dtype=np.uint8)
    h, w = first.shape[:2]
    full = [_ffmpeg(), "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{w}x{h}", "-framerate", cmd["fps"], "-i", "-"] + cmd["out"]
    proc = subprocess.Popen(full, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    n = 0
    try:
        proc.stdin.write(first.tobytes()); n += 1
        for fr in it:
            fr = np.ascontiguousarray(fr, dtype=np.uint8)
            if fr.shape[:2] != (h, w):
                raise ValueError(f"frame {n} has shape {fr.shape[:2]}, expected {(h, w)}")
            proc.stdin.write(fr.tobytes()); n += 1
    except BrokenPipeError:
        pass
    finally:
        try:
            proc.stdin.close()
        except Exception:
            pass
        err = proc.stderr.read().decode(errors="replace"); proc.wait()
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode}): {err.strip()[-400:]}")
    return n


def save_mp4(frames, path, fps=30, crf=18):
    """Encode frames (list or generator of RGB uint8 arrays) to H.264 MP4.

    Frames are streamed to ffmpeg as raw video: no temporary PNG sequence is
    written, and a generator input keeps only one frame in memory at a time.
    """
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _pipe_frames({"fps": str(fps), "out": ["-vf", _EVEN, "-pix_fmt", "yuv420p", "-c:v", "libx264",
                                           "-crf", str(crf), "-movflags", "+faststart", path]}, frames)
    return path


def save_gif(frames, path, fps=30):
    """High-quality GIF (palettegen/paletteuse) in one streamed ffmpeg pass."""
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    vf = f"fps={fps},{_EVEN}:flags=lanczos"
    graph = (f"[0:v]{vf},split[a][b];[a]palettegen=stats_mode=diff[p];"
             f"[b][p]paletteuse=dither=sierra2_4a")
    _pipe_frames({"fps": str(fps), "out": ["-lavfi", graph, "-loop", "0", path]}, frames)
    return path


def save_png(frame, path):
    """Save one RGB frame as PNG (field export)."""
    path = str(path)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(np.asarray(frame, dtype=np.uint8)).save(path)
    return path


def video_info(path):
    """(frames, width, height, fps) of an encoded clip. Uses ffprobe when available and
    otherwise decodes with ffmpeg itself (the packaged app bundles only ffmpeg)."""
    import shutil, json, re
    probe = shutil.which("ffprobe") or str(Path(_ffmpeg()).with_name("ffprobe"))
    if Path(probe).exists():
        out = subprocess.run([probe, "-v", "error", "-select_streams", "v:0", "-count_frames",
                              "-show_entries", "stream=width,height,nb_read_frames,r_frame_rate",
                              "-of", "json", str(path)], capture_output=True, text=True, check=True).stdout
        st = json.loads(out)["streams"][0]
        num, den = st["r_frame_rate"].split("/")
        return int(st["nb_read_frames"]), int(st["width"]), int(st["height"]), float(num) / float(den)
    r = subprocess.run([_ffmpeg(), "-i", str(path), "-map", "0:v:0", "-f", "null", "-"],
                       capture_output=True, text=True)
    err = r.stderr
    m = re.search(r"Stream #0:0.*?(\d{2,5})x(\d{2,5}).*?([\d.]+) fps", err, re.S)
    frames = re.findall(r"frame=\s*(\d+)", err)
    if not m or not frames:
        raise RuntimeError("could not read the clip with ffmpeg: " + err[-300:])
    return int(frames[-1]), int(m.group(1)), int(m.group(2)), float(m.group(3))


def symmetric_limit(field, pct=99.5):
    """A robust symmetric color limit for diverging fields (vorticity)."""
    v = np.percentile(np.abs(field), pct)
    return -v, v


_MPL_LOCK = threading.RLock()      # matplotlib figures are not thread-safe; hold per frame, not per clip
_FIGS = {}


def reuse_figure(key, figsize, dpi):
    """A cached (figure, axes) for repeated frame rendering; the caller clears the axes.
    Must be used under `_MPL_LOCK`."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ent = _FIGS.get(key)
    if ent is None:
        fig = plt.figure(figsize=figsize, dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])
        ent = _FIGS[key] = (fig, ax)
        if len(_FIGS) > 6:                                     # bound the cache
            k0 = next(iter(_FIGS)); f0, _ = _FIGS.pop(k0)
            if k0 != key:
                plt.close(f0)
    return ent


def figure_rgb(fig):
    fig.canvas.draw(); w, h = fig.canvas.get_width_height()
    return np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(h, w, 4)[..., :3].copy()


def streamlines_rgb(ux, uy, cmap=FLOWZOO_EMBER, mask=None, mask_color=SOLID,
                    density=1.1, bg=INK, dpi=100, vmax=None, upscale=2, engine="fast", norm=None):
    """Flow streamlines coloured by speed, as an RGB frame.

    engine="fast" (default): a vectorised numpy integrator + rasteriser (~50× faster
    than matplotlib's streamplot, no figure objects). engine="mpl": matplotlib's
    streamplot, kept for reference renders. Both paint solid cells `mask_color`.
    """
    if engine == "fast":
        return streamlines_fast(ux, uy, cmap=cmap, mask=mask, mask_color=mask_color, density=density,
                                bg=bg, vmax=vmax, upscale=upscale, norm=norm)
    return streamlines_mpl(ux, uy, cmap=cmap, mask=mask, mask_color=mask_color, density=density,
                           bg=bg, dpi=dpi, vmax=vmax)


def streamlines_fast(ux, uy, cmap=FLOWZOO_EMBER, mask=None, mask_color=SOLID, density=1.1,
                     bg=INK, vmax=None, upscale=2, seed_spacing=None, max_len=None, norm=None):
    """Vectorised streamline rendering (numpy only, no figure objects).

    Seeds sit on a regular grid (spacing ≈ 8/density cells). Each is integrated
    forward and backward with RK2 (midpoint) through the bilinearly-interpolated
    field at a fixed arc-length step of one output pixel, so the samples of a
    trace are contiguous when splatted. Like streamplot, a trace stops when it
    enters an occupancy cell already used by another trace (that is what keeps
    the picture evenly filled), at the domain edge, in solid cells, or where the
    speed vanishes. Samples are rasterised onto an `upscale`× canvas, coloured
    by local speed through `cmap`, and lightly softened.
    """
    ny, nx = ux.shape
    U = np.nan_to_num(np.asarray(ux, np.float64)); V = np.nan_to_num(np.asarray(uy, np.float64))
    m = None
    if mask is not None:
        m = np.asarray(mask).astype(bool); U = U.copy(); V = V.copy(); U[m] = 0; V[m] = 0
    spd = np.hypot(U, V)
    if norm is None:
        if vmax is None:
            vmax = float(np.percentile(spd, 99.5)) + 1e-12
        norm = Norm(0.0, vmax)
    vmax = norm.vmax
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    lut = (np.asarray(cmap(np.linspace(0, 1, 256)))[:, :3] * 255).astype(np.uint8)
    sp = seed_spacing or max(3.0, 8.0 / max(density, 0.05))
    sy = np.arange(sp / 2, ny - 0.5, sp); sx = np.arange(sp / 2, nx - 0.5, sp)
    SX, SY = np.meshgrid(sx, sy); seeds = np.column_stack([SX.ravel(), SY.ravel()])
    rng = np.random.default_rng(0); seeds = seeds[rng.permutation(len(seeds))]   # no directional bias in who wins a cell
    if m is not None:
        seeds = seeds[~m[np.clip(seeds[:, 1].round().astype(int), 0, ny - 1),
                         np.clip(seeds[:, 0].round().astype(int), 0, nx - 1)]]
    H, W = ny * upscale, nx * upscale
    step = 1.0 / upscale                                    # one output pixel per sample
    max_len = max_len or int(max(nx, ny) / step)            # a trace may cross the whole domain
    tiny = 1e-3 * vmax + 1e-30
    oc = max(1.0, sp * 0.75)                                # occupancy cell (cells) sets the trace spacing
    occ = np.zeros((int(ny / oc) + 2, int(nx / oc) + 2), bool)
    OW = occ.shape[1]

    def interp(px, py):
        x0 = np.clip(np.floor(px).astype(int), 0, nx - 2); y0 = np.clip(np.floor(py).astype(int), 0, ny - 2)
        fx = np.clip(px - x0, 0, 1); fy = np.clip(py - y0, 0, 1)
        w00 = (1 - fx) * (1 - fy); w10 = fx * (1 - fy); w01 = (1 - fx) * fy; w11 = fx * fy
        u = U[y0, x0] * w00 + U[y0, x0 + 1] * w10 + U[y0 + 1, x0] * w01 + U[y0 + 1, x0 + 1] * w11
        v = V[y0, x0] * w00 + V[y0, x0 + 1] * w10 + V[y0 + 1, x0] * w01 + V[y0 + 1, x0 + 1] * w11
        return u, v

    def cell_of(px, py):
        return (py / oc).astype(int) * OW + (px / oc).astype(int)

    xs_all, ys_all, cs_all = [], [], []
    # Like streamplot, seeds are taken in order and a seed whose cell is already used is
    # skipped. To keep the integration vectorised, seeds are processed in four levels of
    # increasing density (coarse traces first, then the gaps), so long traces are laid
    # down before the space between them is filled.
    iy_s = np.round((seeds[:, 1] - sp / 2) / sp).astype(int); ix_s = np.round((seeds[:, 0] - sp / 2) / sp).astype(int)
    levels = [(iy_s % 4 == 0) & (ix_s % 4 == 0), (iy_s % 2 == 0) & (ix_s % 2 == 0),
              ((iy_s + ix_s) % 2 == 0), np.ones(len(seeds), bool)]
    done = np.zeros(len(seeds), bool)
    for lv in levels:
        pick = lv & ~done; done |= lv
        if not pick.any():
            continue
        sd = seeds[pick]
        c0 = cell_of(sd[:, 0], sd[:, 1]); sd = sd[~occ.flat[c0]]      # skip seeds in used cells
        if not len(sd):
            continue
        occ.flat[cell_of(sd[:, 0], sd[:, 1])] = True
        for sign in (1.0, -1.0):
            px = sd[:, 0].copy(); py = sd[:, 1].copy(); alive = np.ones(len(px), bool)
            cprev = cell_of(px, py)
            for _ in range(max_len):
                u, v = interp(px, py); s_ = np.hypot(u, v)
                inv = sign * step / np.maximum(s_, tiny)
                u2, v2 = interp(px + 0.5 * u * inv, py + 0.5 * v * inv); s2 = np.hypot(u2, v2)
                inv2 = sign * step / np.maximum(s2, tiny)
                nxp = px + u2 * inv2; nyp = py + v2 * inv2
                alive &= (s2 > tiny) & (nxp >= 0) & (nxp <= nx - 1) & (nyp >= 0) & (nyp <= ny - 1)
                if m is not None:
                    alive &= ~m[np.clip(nyp.round().astype(int), 0, ny - 1), np.clip(nxp.round().astype(int), 0, nx - 1)]
                c = cell_of(np.clip(nxp, 0, nx - 1), np.clip(nyp, 0, ny - 1))
                entering = c != cprev
                alive &= ~(entering & occ.flat[c])            # stop at a cell another trace already uses
                if not alive.any():
                    break
                occ.flat[c[alive]] = True; cprev = c
                px = np.where(alive, nxp, px); py = np.where(alive, nyp, py)
                xs_all.append(px[alive]); ys_all.append(py[alive]); cs_all.append(s2[alive])
    img = np.zeros((H, W), np.float32)              # brightness = normalised speed (max-blend)
    if xs_all:
        X = np.concatenate(xs_all); Y = np.concatenate(ys_all)
        C = np.asarray(norm(np.concatenate(cs_all)), np.float32)      # the SAME mapping as the legend (vmin, vmax, gamma)
        ix = np.clip((X * upscale).round().astype(int), 0, W - 1)
        iy = np.clip((Y * upscale).round().astype(int), 0, H - 1)
        for dx_, dy_ in ((0, 0), (1, 0), (0, 1), (1, 1)):
            np.maximum.at(img, (np.clip(iy + dy_, 0, H - 1), np.clip(ix + dx_, 0, W - 1)), 0.25 + 0.75 * C)
    soft = img.copy()
    soft[1:] = np.maximum(soft[1:], 0.55 * img[:-1]); soft[:-1] = np.maximum(soft[:-1], 0.55 * img[1:])
    soft[:, 1:] = np.maximum(soft[:, 1:], 0.55 * img[:, :-1]); soft[:, :-1] = np.maximum(soft[:, :-1], 0.55 * img[:, 1:])
    lit = soft > 0.02
    bgc = np.array(Image.new("RGB", (1, 1), bg))[0, 0]
    rgb = np.empty((H, W, 3), np.uint8); rgb[:] = bgc
    idx = np.clip(((soft - 0.25) / 0.75 * 255).astype(int), 0, 255)
    col = lut[idx]
    a = np.clip(soft / 0.25, 0, 1)[..., None]
    rgb[lit] = (col * a + bgc * (1 - a))[lit].astype(np.uint8)
    if m is not None:
        mc = np.array(Image.new("RGB", (1, 1), mask_color))[0, 0]
        big = np.repeat(np.repeat(m, upscale, 0), upscale, 1)
        rgb[big] = mc
    return rgb[::-1]                                   # +y up, like field_to_rgb


def streamlines_mpl(ux, uy, cmap=FLOWZOO_EMBER, mask=None, mask_color=SOLID,
                    density=1.1, bg=INK, dpi=100, vmax=None):
    """Matplotlib streamplot renderer (figure reused across frames; slower reference)."""
    import matplotlib.pyplot as plt
    ny, nx = ux.shape
    spd = np.sqrt(ux * ux + uy * uy)
    u, v = ux.copy(), uy.copy()
    if mask is not None:
        m = mask.astype(bool); u[m] = 0; v[m] = 0
    cmap = matplotlib.colormaps[cmap] if isinstance(cmap, str) else cmap
    if vmax is None:
        vmax = np.percentile(spd, 99.5) + 1e-12
    lw = 0.6 + 1.1 * np.clip(spd / vmax, 0, 1)
    Y, X = np.mgrid[0:ny, 0:nx]
    with _MPL_LOCK:
        fig, ax = reuse_figure(("stream", nx, ny, dpi), (nx / dpi, ny / dpi), dpi)
        ax.cla(); ax.set_facecolor(bg); fig.patch.set_facecolor(bg)
        try:
            ax.streamplot(X, Y, u, v, color=spd, cmap=cmap, density=density,
                          linewidth=lw, arrowsize=0.7, norm=plt.Normalize(0, vmax))
        except Exception:
            ax.streamplot(X, Y, u, v, color="#7fd0ff", density=density, linewidth=1.0)
        if mask is not None:
            mc = np.array(Image.new("RGB", (1, 1), mask_color))[0, 0] / 255.0
            ov = np.zeros((ny, nx, 4)); ov[m] = [*mc, 1.0]
            ax.imshow(ov, origin="lower", extent=[0, nx, 0, ny], zorder=5)
        ax.set_xlim(0, nx - 1); ax.set_ylim(0, ny - 1); ax.axis("off")
        return figure_rgb(fig)
