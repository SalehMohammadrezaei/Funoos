"""Wrap the recorded app walkthrough into a polished promo:
title card -> walkthrough (with burned-in headlines) -> all-29-scenes tile wall
-> end card.  2560x1440. -> funoos_app_promo.mp4
"""
import glob, os, subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = "/home/impres/Saleh/FlowZoo"
FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, TR = 2560, 1440, 30, 0.6
GAL = os.path.join(ROOT, "results", "gallery")
demo = os.path.join(ROOT, "results", "_demo")
webm = sorted(glob.glob(os.path.join(demo, "rec", "*.webm")), key=os.path.getmtime)[-1]
tmp = os.path.join(demo, "_promo"); os.makedirs(tmp, exist_ok=True)

MOSAIC = ["lbm_cylinder", "ns_smoke", "euler_city", "sph_dam", "spec_kh", "rd_mitosis",
          "lbm_name", "ns_flame", "euler_blast", "sph_waves", "spec_decay", "rd_maze",
          "lbm_f1", "ns_rb", "euler_bubble", "sph_ship", "mix_bands", "rd_spots",
          "lbm_airfoil", "ns_rt", "euler_twin", "sph_slosh", "porous_phi60", "rd_stripes",
          "lbm_cyclist", "ns_chimney", "lbm_peloton", "sph_drop", "sph_pour"]


def run(a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
def dur_of(p): return float(subprocess.check_output([FF.replace("ffmpeg", "ffprobe"), "-v", "error",
    "-show_entries", "format=duration", "-of", "csv=p=0", p]).decode().strip())


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
    center(d, H * 0.56, "a fluid-dynamics studio you can watch", ImageFont.truetype(FR, 56), (226, 233, 247))
    center(d, H * 0.64, "six methods · 29 scenes · run it, switch views, recolour", ImageFont.truetype(FR, 32), (132, 147, 173))


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
    cols, rows = 6, 5; tw, th = W // cols, H // rows
    logo = os.path.join(tmp, "logo_tile.png")
    img = Image.new("RGB", (tw, th), (10, 19, 34)); ImageDraw.Draw(img).text(
        (tw // 2, th // 2), "FUNOOS", font=ImageFont.truetype(FB, 52), fill=(138, 162, 255), anchor="mm")
    img.save(logo)
    n = len(MOSAIC) + 1
    coords = [(c * tw, r * th) for r in range(rows) for c in range(cols)][:n]
    inputs = []
    for k in MOSAIC: inputs += ["-stream_loop", "-1", "-i", os.path.join(GAL, k + ".mp4")]
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", logo]
    parts = [f"[{i}:v]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},setsar=1,fps={FPS}[s{i}]"
             for i in range(len(MOSAIC))]
    parts.append(f"[{len(MOSAIC)}:v]scale={tw}:{th},setsar=1,fps={FPS}[s{len(MOSAIC)}]")
    layout = "|".join(f"{x}_{y}" for x, y in coords)
    parts.append("".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}[wall]")
    post = (f"[wall]drawgrid=w={tw}:h={th}:t=3:color=0x0a1322,"
            f"zoompan=z='min(zoom+0.0003,1.04)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
            f"drawtext=fontfile={FB}:text='29 scenes · one app':fontcolor=white:fontsize=52:x=(w-text_w)/2:y=64"
            ":alpha='if(lt(t,0.5),t/0.5,1)':box=1:boxcolor=0x0a1322@0.6:boxborderw=18,"
            "fade=t=in:st=0:d=0.5[v]")
    run([FF, "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + post, "-map", "[v]",
         "-t", f"{dur}", "-r", str(FPS), "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium",
         "-pix_fmt", "yuv420p", out])


# ---------- normalize walkthrough, build segments ----------
walk = os.path.join(tmp, "walk.mp4")
run([FF, "-y", "-ss", "0.7", "-i", webm, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p",
     "-an", "-c:v", "libx264", "-crf", "17", "-preset", "medium", walk])
wdur = dur_of(walk)

tc, ec = os.path.join(tmp, "title.mp4"), os.path.join(tmp, "end.mp4")
cardvid(os.path.join(tmp, "title.png"), tc, 2.6, True, False)
cardvid(os.path.join(tmp, "end.png"), ec, 3.0, False, True)
mo = os.path.join(tmp, "mosaic.mp4"); build_mosaic(mo, 5.0)

durs = [2.6, wdur, 5.0, 3.0]
o1 = durs[0] - TR
o2 = durs[0] + durs[1] - 2 * TR
o3 = durs[0] + durs[1] + durs[2] - 3 * TR
out = os.path.join(ROOT, "funoos_app_promo.mp4")
fc = (f"[0:v][1:v]xfade=transition=fade:duration={TR}:offset={o1:.2f}[a];"
      f"[a][2:v]xfade=transition=fade:duration={TR}:offset={o2:.2f}[b];"
      f"[b][3:v]xfade=transition=fade:duration={TR}:offset={o3:.2f}[v]")
run([FF, "-y", "-i", tc, "-i", walk, "-i", mo, "-i", ec, "-filter_complex", fc, "-map", "[v]",
     "-c:v", "libx264", "-crf", "17", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
total = sum(durs) - 3 * TR
print(f"DONE -> {out}  ({W}x{H}, ~{total:.0f}s, {os.path.getsize(out)//1024} KB)")
