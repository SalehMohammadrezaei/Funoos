"""Wrap the recorded app walkthrough into a polished promo: title card ->
walkthrough -> end card, clean 1920x1080. -> funoos_app_promo.mp4"""
import glob, os, subprocess
from PIL import Image, ImageDraw, ImageFont

ROOT = "/home/impres/Saleh/FlowZoo"
FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, TR = 1920, 1080, 30, 0.6
demo = os.path.join(ROOT, "results", "_demo")
webm = sorted(glob.glob(os.path.join(demo, "rec", "*.webm")), key=os.path.getmtime)[-1]
tmp = os.path.join(demo, "_promo"); os.makedirs(tmp, exist_ok=True)


def run(a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def card(path, draw_fn):
    img = Image.new("RGB", (W, H), (7, 13, 24)); d = ImageDraw.Draw(img)
    # soft blue vignette glow
    for r, a in [(760, 16), (560, 20), (360, 26)]:
        d.ellipse([W // 2 - r, H // 2 - r - 40, W // 2 + r, H // 2 + r - 40], fill=(19, 34, 74, a))
    draw_fn(d); img.save(path)


def center(d, y, text, font, fill):
    w = d.textlength(text, font=font); d.text(((W - w) / 2, y), text, font=font, fill=fill)


def title(d):
    center(d, H * 0.36, "FUNOOS", ImageFont.truetype(FB, 150), (126, 155, 255))
    center(d, H * 0.56, "a fluid-dynamics studio you can watch", ImageFont.truetype(FR, 44), (226, 233, 247))
    center(d, H * 0.64, "six methods · 29 scenes · run it, switch views, recolour", ImageFont.truetype(FR, 24), (132, 147, 173))


def endcard(d):
    center(d, H * 0.34, "Funoos", ImageFont.truetype(FB, 96), (126, 155, 255))
    center(d, H * 0.50, "github.com/SalehMohammadrezaei/Funoos", ImageFont.truetype(FR, 42), (226, 233, 247))
    center(d, H * 0.58, "free & open source  ·  Saleh Mohammadrezaei", ImageFont.truetype(FR, 24), (132, 147, 173))


card(os.path.join(tmp, "title.png"), title)
card(os.path.join(tmp, "end.png"), endcard)

# normalize the walkthrough (trim the ~0.6s browser-paint lead-in), 1080p, 30fps
walk = os.path.join(tmp, "walk.mp4")
run([FF, "-y", "-ss", "0.6", "-i", webm, "-vf", f"scale={W}:{H}:flags=lanczos,fps={FPS},format=yuv420p",
     "-an", "-c:v", "libx264", "-crf", "18", "-preset", "medium", walk])
wdur = float(subprocess.check_output([FF.replace("ffmpeg", "ffprobe"), "-v", "error",
      "-show_entries", "format=duration", "-of", "csv=p=0", walk]).decode().strip())

# cards -> short clips with fades
def cardvid(png, out, dur, fin, fout):
    vf = f"fps={FPS},format=yuv420p"
    if fin: vf += ",fade=t=in:st=0:d=0.5"
    if fout: vf += f",fade=t=out:st={dur-0.6:.2f}:d=0.6"
    run([FF, "-y", "-loop", "1", "-t", f"{dur}", "-i", png, "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p", out])


tc, ec = os.path.join(tmp, "title.mp4"), os.path.join(tmp, "end.mp4")
cardvid(os.path.join(tmp, "title.png"), tc, 2.6, True, False)
cardvid(os.path.join(tmp, "end.png"), ec, 3.0, False, True)

durs = [2.6, wdur, 3.0]
off1 = durs[0] - TR
off2 = durs[0] + durs[1] - 2 * TR
out = os.path.join(ROOT, "funoos_app_promo.mp4")
fc = (f"[0:v][1:v]xfade=transition=fade:duration={TR}:offset={off1:.2f}[a];"
      f"[a][2:v]xfade=transition=fade:duration={TR}:offset={off2:.2f}[v]")
run([FF, "-y", "-i", tc, "-i", walk, "-i", ec, "-filter_complex", fc, "-map", "[v]",
     "-c:v", "libx264", "-crf", "18", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out])
total = sum(durs) - 2 * TR
print(f"DONE -> {out}  ({W}x{H}, ~{total:.0f}s, {os.path.getsize(out)//1024} KB)")
