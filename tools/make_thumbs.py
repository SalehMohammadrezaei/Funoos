"""Gallery card thumbnails: results/gallery/thumbs/<key>.mp4 + <key>.jpg.

The full gallery clips (results/gallery/<key>.mp4) carry a colour bar and keep the field's
aspect ratio, which ranges from 0.74 (candle flame) to 40 (Sod tube). On a 16:10 card that
leaves a thin, dark strip. A thumbnail is made for the card only:

* the colour-bar panel added by render.add_colorbar is cropped away (its divider is located
  in the frame; clips without a bar are left whole);
* very wide fields (aspect > 2) are cut to a 2:1 window at the inflow side, where the obstacle
  and the start of the wake are; one-dimensional strips (aspect >= 8) are stretched vertically,
  which is exact for a field that is uniform across the tube;
* the field is fitted into 480x300 over a blurred, darkened copy of itself (no black bands),
  with a mild gamma lift so dark palettes read at card size;
* the poster is a developed frame (70 % of the clip), not the initial state.

The colours of the thumbnails are decorative; the Detail page and Studio show the full,
unmodified clips with their colour bars.

    python tools/make_thumbs.py            # representatives of all experiments
    python tools/make_thumbs.py --all      # every scene
    python tools/make_thumbs.py lbm_cylinder,sph_dam
"""
import io
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import catalog, render  # noqa: E402

GAL = ROOT / "results" / "gallery"
OUT = GAL / "thumbs"
TW, TH = 480, 300
DIVIDER = np.array([40, 50, 80], float)
PANEL_BG = np.array([12, 15, 26], float)


def _ff():
    return render._ffmpeg()


def frame_at(mp4, t):
    png = subprocess.run([_ff(), "-v", "error", "-ss", f"{t:.3f}", "-i", str(mp4), "-frames:v", "1",
                          "-f", "image2pipe", "-vcodec", "png", "-"], check=True, capture_output=True).stdout
    return np.asarray(Image.open(io.BytesIO(png)).convert("RGB"), float)


def duration(mp4):
    info = render.video_info(str(mp4)) if hasattr(render, "video_info") else {}
    d = info.get("duration") if isinstance(info, dict) else None
    if d:
        return float(d)
    err = subprocess.run([_ff(), "-i", str(mp4)], capture_output=True, text=True).stderr
    for line in err.splitlines():
        if "Duration:" in line:
            h, m, s = line.split("Duration:")[1].split(",")[0].strip().split(":")
            return int(h) * 3600 + int(m) * 60 + float(s)
    return 3.0


def field_width(img):
    """Width of the field inside a frame, i.e. where render.add_colorbar's panel starts."""
    H, T = img.shape[:2]
    guesses = {int(round(T / 1.16)), T - 104}
    best, best_err = None, 1e9
    for g in guesses:
        for x in range(max(1, g - 10), min(T - 2, g + 11)):
            col_err = np.abs(img[:, x] - DIVIDER).sum(axis=1).mean()
            right = img[:, x + 2:, :]
            bg_share = (np.abs(right - PANEL_BG).sum(axis=2) < 30).mean() if right.size else 0.0
            if col_err < 40 and bg_share > 0.55 and col_err < best_err:
                best, best_err = x, col_err
    return best if best is not None else T


def make(key):
    src = GAL / f"{key}.mp4"
    if not src.exists():
        print(f"  - {key}: no clip"); return False
    dur = duration(src)
    img = frame_at(src, min(1.0, dur * 0.3))
    H = img.shape[0]; W = field_width(img); aspect = W / H
    if aspect >= 8:                                     # 1-D strip: stretch across the card
        fc = f"[0:v]crop={W}:{H}:0:0,scale={TW}:{TH}:flags=bicubic,eq=gamma=1.12,format=yuv420p[v]"
    else:
        cw = int(min(W, 2.0 * H)) if aspect > 2.0 else W
        cw -= cw % 2; hh = H - H % 2
        fc = (f"[0:v]crop={cw}:{hh}:0:0,split[a][b];"
              f"[a]scale={TW}:{TH}:force_original_aspect_ratio=increase,crop={TW}:{TH},gblur=sigma=18,eq=brightness=-0.10:saturation=1.05[bg];"
              f"[b]scale={TW}:{TH}:force_original_aspect_ratio=decrease:flags=lanczos,eq=gamma=1.12:saturation=1.08[fg];"
              f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[v]")
    OUT.mkdir(parents=True, exist_ok=True)
    mp4 = OUT / f"{key}.mp4"; jpg = OUT / f"{key}.jpg"
    subprocess.run([_ff(), "-v", "error", "-y", "-i", str(src), "-filter_complex", fc, "-map", "[v]", "-an",
                    "-c:v", "libx264", "-crf", "26", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    str(mp4)], check=True)
    subprocess.run([_ff(), "-v", "error", "-y", "-ss", f"{dur * 0.7:.2f}", "-i", str(mp4), "-frames:v", "1", "-q:v", "3",
                    str(jpg)], check=True)
    print(f"  ✓ {key}: field {W}x{H} (aspect {aspect:.2f}{', bar cropped' if W < img.shape[1] else ''}) -> "
          f"{mp4.stat().st_size // 1024} KB")
    return True


def main(argv):
    if argv and argv[0] == "--all":
        keys = [s["key"] for s in catalog.SCENES]
    elif argv:
        keys = argv[0].split(",")
    else:
        keys = [e["representative"] for e in catalog.EXPERIMENTS]
    bad = [k for k in keys if not make(k)]
    if bad:
        print("missing clips:", ", ".join(bad)); return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
