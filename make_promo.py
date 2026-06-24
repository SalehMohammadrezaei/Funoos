"""Build a polished promo reel for Funoos from the gallery clips → funoos_promo.mp4.
   title card → crossfaded montage (lower-third labels) → end card.  1280x720, 30fps.
"""
import os, subprocess, tempfile
import matplotlib; matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch  # noqa

FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, DUR, TR = 1280, 720, 30, 3.4, 0.55
ROOT = os.path.dirname(os.path.abspath(__file__)); GAL = os.path.join(ROOT, "results", "gallery")
TMP = tempfile.mkdtemp(prefix="promo_")

SCENES = [
    ("lbm_name",     "Flow Around Your Name",      "Lattice–Boltzmann"),
    ("lbm_f1",       "F1 Car Aerodynamics",        "Lattice–Boltzmann"),
    ("ns_flame",     "Candle Flame",               "Navier–Stokes  ·  diffusion flame"),
    ("euler_city",   "Shockwave Hits a City",      "Compressible Euler  ·  HLLC"),
    ("sph_dam",      "Dam Break",                  "Smoothed-Particle Hydrodynamics"),
    ("spec_kh",      "Kelvin–Helmholtz Billows",   "Pseudo-spectral  ·  FFT"),
    ("ns_rb",        "Rayleigh–Bénard Convection", "Navier–Stokes  ·  Boussinesq"),
    ("rd_mitosis",   "Turing Patterns: Mitosis",   "Reaction–Diffusion  ·  Gray–Scott"),
    ("porous_phi60", "Flow Through Porous Rock",   "Lattice–Boltzmann  ·  permeability"),
    ("lbm_cylinder", "Kármán Vortex Street",       "Lattice–Boltzmann  ·  St ≈ 0.2"),
]


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def card(path, draw):
    fig = plt.figure(figsize=(W / 100, H / 100), dpi=100)
    fig.patch.set_facecolor("#070d18")
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor("#070d18"); ax.axis("off")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    # soft blue glow
    ax.scatter([0.5], [0.56], s=560000, c="#13346a", alpha=0.30, edgecolors="none", zorder=0)
    draw(ax)
    fig.savefig(path, dpi=100); plt.close(fig)


def title(ax):
    ax.text(0.5, 0.60, "FUNOOS", ha="center", va="center", fontsize=92, fontweight="bold",
            color="#7e9bff", family="DejaVu Sans")
    ax.text(0.5, 0.43, "an interactive playground for the classic methods of fluid simulation",
            ha="center", va="center", fontsize=20, color="#cdd9f2")
    ax.text(0.5, 0.34, "six solvers · 29 scenes · click, tweak, watch", ha="center", va="center",
            fontsize=14, color="#7e8eaa")


def outro(ax):
    ax.text(0.5, 0.60, "Funoos", ha="center", va="center", fontsize=58, fontweight="bold", color="#7e9bff")
    ax.text(0.5, 0.46, "github.com/SalehMohammadrezaei/Funoos", ha="center", va="center",
            fontsize=24, color="#cdd9f2")
    ax.text(0.5, 0.36, "free & open source  ·  made by Saleh Mohammadrezaei", ha="center", va="center",
            fontsize=15, color="#7e8eaa")


def card_video(png, out, dur, fade_in, fade_out):
    vf = f"fps={FPS},format=yuv420p"
    if fade_in:  vf += ",fade=t=in:st=0:d=0.6"
    if fade_out: vf += f",fade=t=out:st={dur-0.7:.2f}:d=0.7"
    run([FF, "-y", "-loop", "1", "-t", f"{dur}", "-i", png, "-vf", vf,
         "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


def scene_seg(key, name, method, out):
    nf = os.path.join(TMP, key + "_n.txt"); mf = os.path.join(TMP, key + "_m.txt")
    open(nf, "w").write(name); open(mf, "w").write(method)
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x070d18,setsar=1,fps={FPS},"
          f"drawbox=x=0:y={H-150}:w={W}:h=150:color=0x050a14@0.55:t=fill,"
          f"drawtext=fontfile={FB}:textfile={nf}:fontcolor=white:fontsize=44:x=64:y={H-120}:borderw=2:bordercolor=black@0.5,"
          f"drawtext=fontfile={FR}:textfile={mf}:fontcolor=0x9db4f0:fontsize=25:x=66:y={H-62}")
    run([FF, "-y", "-i", os.path.join(GAL, key + ".mp4"), "-t", f"{DUR}", "-an", "-vf", vf,
         "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


print("building cards…")
card(os.path.join(TMP, "title.png"), title); card(os.path.join(TMP, "outro.png"), outro)
segs, durs = [], []
t = os.path.join(TMP, "00_title.mp4"); card_video(os.path.join(TMP, "title.png"), t, 2.8, True, False)
segs.append(t); durs.append(2.8)
print("building scene segments…")
for i, (k, n, m) in enumerate(SCENES):
    s = os.path.join(TMP, f"{i+1:02d}_{k}.mp4"); scene_seg(k, n, m, s); segs.append(s); durs.append(DUR)
    print("  ", k)
o = os.path.join(TMP, "99_outro.mp4"); card_video(os.path.join(TMP, "outro.png"), o, 3.0, False, True)
segs.append(o); durs.append(3.0)

print("crossfading…")
inputs = []
for s in segs: inputs += ["-i", s]
fc = []; prev = "0:v"; off = 0.0
for k in range(1, len(segs)):
    off += durs[k - 1] - TR
    lab = "vout" if k == len(segs) - 1 else f"v{k}"
    fc.append(f"[{prev}][{k}:v]xfade=transition=fade:duration={TR}:offset={off:.3f}[{lab}]")
    prev = lab
out_mp4 = os.path.join(ROOT, "funoos_promo.mp4")
run([FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]",
     "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4])
total = sum(durs) - TR * (len(segs) - 1)
print(f"DONE -> {out_mp4}  (~{total:.0f}s, {os.path.getsize(out_mp4)//1024} KB)")
