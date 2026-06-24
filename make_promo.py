"""Build a motion-graphics promo reel for Funoos -> funoos_promo.mp4.

Animated title over live flow -> Ken-Burns + vignette montage with kinetic
slide-in lower-thirds -> animated end card.  Varied directional transitions.
1280x720, 30fps.  Built from the gallery clips with ffmpeg (per-frame drawtext
expressions for the animation).  Reproducible: `python make_promo.py`.
"""
import os, subprocess, tempfile

FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, DUR, TR = 1280, 720, 30, 3.3, 0.6
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
# tasteful, mostly-smooth transition rotation (one per cut: intro->s1, s1->s2, ... s10->outro)
TRANS = ["smoothleft", "dissolve", "smoothup", "circleopen", "smoothright",
         "dissolve", "wipeleft", "fadeblack", "smoothleft", "dissolve", "circleclose"]


def run(args):
    subprocess.run(args, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)


def enc(in_args, vf, dur, out):
    run([FF, "-y", *in_args, "-t", f"{dur}", "-an", "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


# ---- animated title: FUNOOS scales+fades in over live flow, tagline slides up ----
def intro(out):
    dur = 4.2
    vf = (
        # abstract turbulence backdrop; crop off the baked-in colorbar, then cover-scale
        f"crop=iw*0.85:ih:0:0,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.30:saturation=1.18,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.42:t=fill,"
        # FUNOOS — scale-in (fontsize ramp) + alpha fade, recentred each frame
        f"drawtext=fontfile={FB}:text='FUNOOS':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.85),58+80*(t/0.85),138)':x=(w-text_w)/2:y=(h-text_h)/2-24"
        ":alpha='if(lt(t,0.2),0,if(lt(t,0.85),(t-0.2)/0.65,1))':shadowcolor=black@0.55:shadowx=0:shadowy=3,"
        # tagline — slides up + fades in
        f"drawtext=fontfile={FR}:text='an interactive playground for the classic methods of fluid simulation'"
        ":fontcolor=0xe2e9f7:fontsize=25:x=(w-text_w)/2"
        ":y='h*0.605+24*(1-min(max((t-0.95)/0.7,0),1))'"
        ":alpha='if(lt(t,0.95),0,if(lt(t,1.65),(t-0.95)/0.7,1))',"
        # third line — fades in last
        f"drawtext=fontfile={FR}:text='six solvers · 29 scenes · click, tweak, watch'"
        ":fontcolor=0x8493ad:fontsize=15:x=(w-text_w)/2:y=h*0.675"
        ":alpha='if(lt(t,1.7),0,if(lt(t,2.4),(t-1.7)/0.7,1))',"
        "vignette,fade=t=in:st=0:d=0.4,fade=t=out:st=3.55:d=0.65"
    )
    enc(["-stream_loop", "-1", "-i", os.path.join(GAL, "spec_decay.mp4")], vf, dur, out)


# ---- scene: Ken-Burns zoom + vignette + kinetic slide-in lower-third ----
def scene(key, name, method, out):
    nf = os.path.join(TMP, key + "_n.txt"); mf = os.path.join(TMP, key + "_m.txt")
    open(nf, "w").write(name); open(mf, "w").write(method)
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
        f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x070d18,setsar=1,fps={FPS},"
        f"zoompan=z='min(zoom+0.0006,1.085)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
        "vignette,"
        f"drawbox=x=0:y={H-150}:w={W}:h=150:color=0x050a14@0.55:t=fill,"
        f"drawbox=x=60:y={H-120}:w=5:h=58:color=0x8aa2ff@0.95:t=fill,"
        # name slides in from the left + fades
        f"drawtext=fontfile={FB}:textfile={nf}:fontcolor=white:fontsize=44"
        f":x='84-46*(1-min(max(t/0.5,0),1))':y={H-120}"
        ":alpha='if(lt(t,0.5),t/0.5,1)':borderw=2:bordercolor=black@0.5,"
        # method slides in slightly later
        f"drawtext=fontfile={FR}:textfile={mf}:fontcolor=0x9db4f0:fontsize=25"
        f":x='84-46*(1-min(max((t-0.12)/0.5,0),1))':y={H-60}"
        ":alpha='if(lt(t,0.12),0,if(lt(t,0.62),(t-0.12)/0.5,1))'"
    )
    enc(["-i", os.path.join(GAL, key + ".mp4")], vf, DUR, out)


# ---- animated end card over a turbulence backdrop ----
def outro(out):
    dur = 3.7
    bg = "spec_decay" if os.path.exists(os.path.join(GAL, "spec_decay.mp4")) else "lbm_cylinder"
    vf = (
        # same turbulence backdrop as the intro (bookend); crop colorbar, mirror for variety
        f"crop=iw*0.85:ih:0:0,hflip,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.34:saturation=1.10,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.50:t=fill,"
        f"drawtext=fontfile={FB}:text='Funoos':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.7),60+18*(t/0.7),78)':x=(w-text_w)/2:y=h*0.40"
        ":alpha='if(lt(t,0.15),0,if(lt(t,0.7),(t-0.15)/0.55,1))':shadowcolor=black@0.5:shadowx=0:shadowy=3,"
        f"drawtext=fontfile={FR}:text='github.com/SalehMohammadrezaei/Funoos'"
        ":fontcolor=0xe2e9f7:fontsize=26:x=(w-text_w)/2:y='h*0.55+18*(1-min(max((t-0.7)/0.6,0),1))'"
        ":alpha='if(lt(t,0.7),0,if(lt(t,1.3),(t-0.7)/0.6,1))',"
        f"drawtext=fontfile={FR}:text='free & open source · made by Saleh Mohammadrezaei'"
        ":fontcolor=0x8493ad:fontsize=15:x=(w-text_w)/2:y=h*0.63"
        ":alpha='if(lt(t,1.3),0,if(lt(t,1.9),(t-1.3)/0.6,1))',"
        "vignette,fade=t=in:st=0:d=0.5,fade=t=out:st=2.95:d=0.7"
    )
    enc(["-stream_loop", "-1", "-i", os.path.join(GAL, bg + ".mp4")], vf, dur, out)


segs, durs = [], []
print("intro…");  it = os.path.join(TMP, "00_intro.mp4"); intro(it); segs.append(it); durs.append(4.2)
print("scenes…")
for i, (k, n, m) in enumerate(SCENES):
    s = os.path.join(TMP, f"{i+1:02d}_{k}.mp4"); scene(k, n, m, s); segs.append(s); durs.append(DUR); print("  ", k)
print("outro…"); ot = os.path.join(TMP, "99_outro.mp4"); outro(ot); segs.append(ot); durs.append(3.7)

print("transitions…")
inputs = []
for s in segs: inputs += ["-i", s]
fc = []; prev = "0:v"; off = 0.0
for k in range(1, len(segs)):
    off += durs[k - 1] - TR
    tr = TRANS[(k - 1) % len(TRANS)]
    lab = "vout" if k == len(segs) - 1 else f"v{k}"
    fc.append(f"[{prev}][{k}:v]xfade=transition={tr}:duration={TR}:offset={off:.3f}[{lab}]")
    prev = lab
out_mp4 = os.path.join(ROOT, "funoos_promo.mp4")
run([FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", "[vout]",
     "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4])
total = sum(durs) - TR * (len(segs) - 1)
print(f"DONE -> {out_mp4}  (~{total:.0f}s, {os.path.getsize(out_mp4)//1024} KB)")
