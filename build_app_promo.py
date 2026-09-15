"""Wrap the recorded app walkthrough into a polished promo:
title card -> walkthrough (tools/record_walkthrough.py) -> tile wall of the 27 experiments
-> end card.  2560x1440. -> funoos_app_promo.mp4
"""
from pathlib import Path
import glob, os, shutil, subprocess, sys
from PIL import Image, ImageDraw, ImageFont

ROOT = str(Path(__file__).resolve().parent)
sys.path.insert(0, str(Path(__file__).resolve().parent))
from flowzoo import render as _render   # noqa: E402
FF = shutil.which("ffmpeg") or _render._ffmpeg()
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, TR = 2560, 1440, 30, 0.6
GAL = os.path.join(ROOT, "results", "gallery")
demo = os.environ.get("FUNOOS_PROMO_WORK") or os.path.join(ROOT, "results", "_demo")
webm = sorted(glob.glob(os.path.join(demo, "rec", "*.webm")), key=os.path.getmtime)[-1]
tmp = os.path.join(demo, "_promo"); os.makedirs(tmp, exist_ok=True)

MOSAIC = [e["representative"] for e in __import__("flowzoo.catalog", fromlist=["EXPERIMENTS"]).EXPERIMENTS]        # one tile per experiment (card thumbnails)


def run(a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
def dur_of(p):
    out = subprocess.run([FF, "-i", p], capture_output=True, text=True).stderr
    h, m, s_ = out.split("Duration:")[1].split(",")[0].strip().split(":")
    return int(h) * 3600 + int(m) * 60 + float(s_)


# ---------- cards ----------
def card(path, draw_fn):
    img = Image.new("RGB", (W, H), (7, 13, 24)); d = ImageDraw.Draw(img)
    for r, a in [(1000, 16), (720, 20), (460, 26)]:
        d.ellipse([W // 2 - r, H // 2 - r - 50, W // 2 + r, H // 2 + r - 50], fill=(19, 34, 74, a))
    draw_fn(d); img.save(path)


def center(d, y, text, font, fill):
    w = d.textlength(text, font=font); d.text(((W - w) / 2, y), text, font=font, fill=fill)


def title(d):
    center(d, H * 0.35, "FUNOOS", ImageFont.truetype(FB, 200), (126, 155, 255))
    center(d, H * 0.56, "explore fluid motion through simulation", ImageFont.truetype(FR, 56), (226, 233, 247))
    center(d, H * 0.64, "27 experiments · 48 presets · run it, switch views, recolour, measure", ImageFont.truetype(FR, 32), (132, 147, 173))


def endcard(d):
    center(d, H * 0.34, "Funoos", ImageFont.truetype(FB, 128), (126, 155, 255))
    center(d, H * 0.50, "github.com/SalehMohammadrezaei/Funoos", ImageFont.truetype(FR, 54), (226, 233, 247))
    center(d, H * 0.58, "free & open source  ·  Saleh Mohammadrezaei", ImageFont.truetype(FR, 32), (132, 147, 173))


card(os.path.join(tmp, "title.png"), title)
card(os.path.join(tmp, "end.png"), endcard)


def cardvid(png, out, dur, fin, fout):
    vf = f"fps={FPS},format=yuv420p"
    if fin: vf += ",fade=t=in:st=0:d=0.5"
    if fout: vf += f",fade=t=out:st={dur-0.6:.2f}:d=0.6"
    run([FF, "-y", "-loop", "1", "-t", f"{dur}", "-i", png, "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "17", "-pix_fmt", "yuv420p", out])


# ---------- all-29-scenes tile wall ----------
def build_mosaic(out, dur):
    cols, rows = 7, 4; tw, th = W // cols, H // rows
    logo = os.path.join(tmp, "logo_tile.png")
    img = Image.new("RGB", (tw, th), (10, 19, 34)); ImageDraw.Draw(img).text(
        (tw // 2, th // 2), "FUNOOS", font=ImageFont.truetype(FB, 52), fill=(138, 162, 255), anchor="mm")
    img.save(logo)
    n = len(MOSAIC) + 1
    coords = [(c * tw, r * th) for r in range(rows) for c in range(cols)][:n]
    inputs = []
    for k in MOSAIC:
        th_clip = os.path.join(GAL, "thumbs", k + ".mp4")
        inputs += ["-stream_loop", "-1", "-i", th_clip if os.path.exists(th_clip) else os.path.join(GAL, k + ".mp4")]
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", logo]
    # blurred-fill each tile so the WHOLE scene shows (no cropping)
    parts = []
    for i in range(len(MOSAIC)):
        parts.append(
            f"[{i}:v]fps={FPS},split[b{i}][f{i}];"
            f"[b{i}]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},gblur=sigma=7[bb{i}];"
            f"[f{i}]scale={tw-10}:{th-10}:force_original_aspect_ratio=decrease[ff{i}];"
            f"[bb{i}][ff{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[s{i}]")
    parts.append(f"[{len(MOSAIC)}:v]scale={tw}:{th},setsar=1,fps={FPS}[s{len(MOSAIC)}]")
    layout = "|".join(f"{x}_{y}" for x, y in coords)
    parts.append("".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}[wall]")
    post = (f"[wall]drawgrid=w={tw}:h={th}:t=3:color=0x0a1322,"
            f"zoompan=z='min(zoom+0.0003,1.04)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
            f"drawtext=fontfile={FB}:text='27 experiments · one app':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=64"
            ":alpha='if(lt(t,0.5),t/0.5,1)':box=1:boxcolor=0x0a1322@0.6:boxborderw=18,"
            "fade=t=in:st=0:d=0.5[v]")
    run([FF, "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + post, "-map", "[v]",
         "-t", f"{dur}", "-r", str(FPS), "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", out])


# ---------- featured scene shown large (blurred-fill, whole scene) ----------
def featured(key, name, method, out, dur):
    nf = os.path.join(tmp, "f_" + key + "_n.txt"); open(nf, "w").write(name)
    mf = os.path.join(tmp, "f_" + key + "_m.txt"); open(mf, "w").write(method)
    clip = os.path.join(GAL, key + ".mp4")
    fc = (f"[0:v]fps={FPS},split[bg][fg];"
          f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma=26,eq=brightness=-0.13:saturation=1.05[bgb];"
          f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fgs];"
          f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,"
          f"drawbox=x=0:y={H-190}:w={W}:h=190:color=0x050a14@0.5:t=fill,"
          f"drawbox=x=90:y={H-158}:w=8:h=96:color=0x8aa2ff@0.95:t=fill,"
          f"drawtext=fontfile={FB}:textfile={nf}:fontcolor=white:fontsize=58:x=124:y={H-156}"
          ":alpha='if(lt(t,0.4),t/0.4,1)':borderw=2:bordercolor=black@0.5,"
          f"drawtext=fontfile={FR}:textfile={mf}:fontcolor=0x9db4f0:fontsize=32:x=126:y={H-84}"
          ":alpha='if(lt(t,0.5),t/0.5,1)'[v]")
    run([FF, "-y", "-stream_loop", "-1", "-i", clip, "-t", f"{dur}", "-filter_complex", fc, "-map", "[v]",
         "-r", str(FPS), "-an", "-c:v", "libx264", "-crf", "17", "-preset", "medium", "-pix_fmt", "yuv420p", out])


# ---------- normalize walkthrough, build segments ----------
walk = os.path.join(tmp, "walk.mp4")
run([FF, "-y", "-ss", "0.7", "-i", webm, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p",
     "-an", "-c:v", "libx264", "-crf", "17", "-preset", "medium", walk])
wdur = dur_of(walk)

tc, ec = os.path.join(tmp, "title.mp4"), os.path.join(tmp, "end.mp4")
cardvid(os.path.join(tmp, "title.png"), tc, 2.6, True, False)
cardvid(os.path.join(tmp, "end.png"), ec, 3.0, False, True)
mo = os.path.join(tmp, "mosaic.mp4"); build_mosaic(mo, 6.0)

# spotlight a few scenes large after the wall
FEAT = [("ns_smoke", "Rising smoke", "Incompressible Navier–Stokes"),
        ("ns_rb", "Heated-layer convection", "Incompressible Navier–Stokes"),
        ("sph_ship", "Floating hull", "Smoothed-Particle Hydrodynamics"),
        ("rd_spots", "Gray–Scott patterns", "Reaction–Diffusion")]
feats = []
for k, n, m in FEAT:
    fo = os.path.join(tmp, "feat_" + k + ".mp4"); featured(k, n, m, fo, 3.0); feats.append(fo)

# assemble: title -> walkthrough -> tile wall -> featured scenes -> end card
segs = [tc, walk, mo] + feats + [ec]
durs = [2.6, wdur, 6.0] + [3.0] * len(feats) + [3.0]
inputs = []
for s in segs: inputs += ["-i", s]
fc = []; prev = "0:v"; off = 0.0
for k in range(1, len(segs)):
    off += durs[k - 1] - TR
    lab = "v" if k == len(segs) - 1 else f"v{k}"
    fc.append(f"[{prev}][{k}:v]xfade=transition=fade:duration={TR}:offset={off:.2f}[{lab}]"); prev = lab
out = os.path.join(ROOT, "docs", "funoos_app_promo.mp4")
run([FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[v]",
     "-c:v", "libx264", "-crf", "20", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
total = sum(durs) - TR * (len(segs) - 1)
print(f"DONE -> {out}  ({W}x{H}, ~{total:.0f}s, {os.path.getsize(out)//1024} KB)")
