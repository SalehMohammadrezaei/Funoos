"""High-quality 1080p product film for Funoos -> funoos_promo.mp4.

Shows what the app does, across DIFFERENT cases:
  • MANY WAYS TO SEE IT — a different view on a different scene
      (cylinder→vorticity, airfoil→streamlines, Bénard→speed, smoke→dye)
  • RECOLOR INSTANTLY — one field (Kelvin–Helmholtz) cycled through palettes
  • EXPLORE — all 29 scenes as a live tile wall
Every shot uses a blurred-fill background so the whole scene shows fully (no
black bands, nothing cropped).  Footage rendered fresh & high-res via lossless
PNG sequences.  Clean grade — no bloom/vignette/scope bars.
Run: ./.venv/bin/python make_promo.py
"""
import os, subprocess, tempfile, numpy as np
from PIL import Image, ImageDraw, ImageFont
import flowzoo.engine as E, flowzoo.render as R, flowzoo.catalog as C

FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, FS, TR = 1920, 1080, 30, 28, 0.7
ROOT = os.path.dirname(os.path.abspath(__file__)); GAL = os.path.join(ROOT, "results", "gallery")
TMP = tempfile.mkdtemp(prefix="promo_")
SC = {s["key"]: s for s in C.SCENES}

# (scene key, view, colormap, dump name, solve resolution, dump seconds)
# full-field, moderate-aspect cases so each view fills the frame (no dark bands)
VIEWSHOTS = [
    ("spec_decay",   "Vorticity",   "Curl (cyan–amber)", "Vorticity",   "High", 4.6),  # also intro/outro bg
    ("ns_rb",        "Speed",       "Ocean (water)",     "Speed",       "High", 3.2),
    ("porous_phi60", "Streamlines", "Turbo",             "Streamlines", "High", 3.2),
    ("euler_blast",  "Schlieren",   "Smoke (mono)",      "Schlieren",   "High", 3.2),
]
SHOTSUB = {"Vorticity": "2-D turbulence · pseudo-spectral", "Speed": "Rayleigh–Bénard · Navier–Stokes",
           "Streamlines": "flow through rock · lattice-Boltzmann", "Schlieren": "open-air blast · compressible Euler"}
RECOLOR = [("Curl (cyan–amber)", "Curl"), ("Inferno", "Inferno"), ("Twilight", "Twilight"), ("Turbo", "Turbo")]
MOSAIC = ["lbm_cylinder", "ns_smoke", "euler_city", "sph_dam", "spec_kh", "rd_mitosis",
          "lbm_name", "ns_flame", "euler_blast", "sph_waves", "spec_decay", "rd_maze",
          "lbm_f1", "ns_rb", "euler_bubble", "sph_ship", "mix_bands", "rd_spots",
          "lbm_airfoil", "ns_rt", "euler_twin", "sph_slosh", "porous_phi60", "rd_stripes",
          "lbm_cyclist", "ns_chimney", "lbm_peloton", "sph_drop", "sph_pour"]


def run(a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
def src(d): return ["-framerate", str(FS), "-i", os.path.join(d, "f_%05d.png")]


def dump(frames, name, dur):
    d = os.path.join(TMP, name); os.makedirs(d, exist_ok=True)
    fr = [np.asarray(f) for f in frames]; need = int(dur * FS) + 6; n = 0
    while n < need:
        for f in fr:
            Image.fromarray(f).save(os.path.join(d, f"f_{n:05d}.png")); n += 1
            if n >= need: break
    return d


def solve_scene(key, resolution):
    s = SC[key]; name = s["exhibit"]
    p = {q["name"]: q["default"] for q in E.EXHIBITS[name]["params"]}
    p.update(s["preset"]); p["resolution"] = resolution
    return E.solve_exhibit(name, p)


# ---------- render footage (or reuse via PROMO_REUSE) ----------
REUSE = os.environ.get("PROMO_REUSE")
dirs = {}
if REUSE:
    for _, _, _, nm, _, _ in VIEWSHOTS: dirs[nm] = os.path.join(REUSE, nm)
    for _, short in RECOLOR: dirs["rc_" + short] = os.path.join(REUSE, "rc_" + short)
    print("reusing render dirs from", REUSE)
else:
    for key, view, cm, nm, res, dd in VIEWSHOTS:
        print(f"solving {key} @ {res} → {view}…")
        dirs[nm] = dump(solve_scene(key, res).render(view, cm), nm, dd)
    print("solving spec_kh @ High → recolor…")
    kh = solve_scene("spec_kh", "High")
    for cm, short in RECOLOR:
        dirs["rc_" + short] = dump(kh.render("Vorticity", cm), "rc_" + short, 2.6)

# the turbulence-vorticity clip doubles as the intro/outro backdrop
BG = dirs["Vorticity"]


# ---------- blurred-fill: whole scene sharp & centred over a blurred copy ----------
def fill_chain(label_in, label_out, blur=24, dark=-0.14):
    return (f"[{label_in}]fps={FPS},split[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},gblur=sigma={blur},"
            f"eq=brightness={dark}:saturation=1.05[bgb];"
            f"[fg]scale={W}:{H}:force_original_aspect_ratio=decrease:flags=lanczos[fgs];"
            f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2[{label_out}]")


def seg(d, out, dur, chip, sub, chapter=None):
    nf = os.path.join(TMP, os.path.basename(out) + "_n.txt"); open(nf, "w").write(chip)
    mf = os.path.join(TMP, os.path.basename(out) + "_m.txt"); open(mf, "w").write(sub)
    post = [f"zoompan=z='min(zoom+0.0004,1.06)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}",
            f"drawbox=x=0:y={H-210}:w={W}:h=185:color=0x050a14@0.5:t=fill",
            f"drawbox=x=90:y={H-188}:w=8:h=100:color=0x8aa2ff@0.95:t=fill",
            (f"drawtext=fontfile={FB}:textfile={nf}:fontcolor=white:fontsize=58"
             f":x='124-46*(1-min(max(t/0.5,0),1))':y={H-188}:alpha='if(lt(t,0.5),t/0.5,1)':borderw=2:bordercolor=black@0.5"),
            (f"drawtext=fontfile={FR}:textfile={mf}:fontcolor=0x9db4f0:fontsize=32"
             f":x='126-46*(1-min(max((t-0.12)/0.5,0),1))':y={H-110}"
             ":alpha='if(lt(t,0.12),0,if(lt(t,0.62),(t-0.12)/0.5,1))'")]
    if chapter:
        post.append(f"drawtext=fontfile={FB}:text='{chapter}':fontcolor=0x8aa2ff:fontsize=30:x=96:y=112"
                    f":alpha='if(lt(t,0.4),t/0.4,if(lt(t,{dur-0.5:.2f}),1,({dur:.2f}-t)/0.5))'")
    fc = fill_chain("0:v", "base") + ";[base]" + ",".join(post) + "[v]"
    run([FF, "-y", *src(d), "-t", f"{dur}", "-filter_complex", fc, "-map", "[v]", "-r", str(FPS),
         "-an", "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p", out])


def intro(out):
    dur = 4.4
    vf = (
        f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.24:saturation=1.14,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.38:t=fill,"
        f"drawtext=fontfile={FB}:text='FUNOOS':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.9),90+110*(t/0.9),200)':x=(w-text_w)/2:y=(h-text_h)/2-30"
        ":alpha='if(lt(t,0.25),0,if(lt(t,0.9),(t-0.25)/0.65,1))':shadowcolor=black@0.55:shadowx=0:shadowy=4,"
        f"drawtext=fontfile={FR}:text='a fluid-dynamics studio you can watch'"
        ":fontcolor=0xe6ecf9:fontsize=40:x=(w-text_w)/2:y='h*0.60+26*(1-min(max((t-1.0)/0.7,0),1))'"
        ":alpha='if(lt(t,1.0),0,if(lt(t,1.7),(t-1.0)/0.7,1))',"
        f"drawtext=fontfile={FR}:text='run it · switch how you see it · recolor · measure'"
        ":fontcolor=0x8493ad:fontsize=22:x=(w-text_w)/2:y=h*0.685"
        ":alpha='if(lt(t,1.8),0,if(lt(t,2.5),(t-1.8)/0.7,1))',"
        "fade=t=in:st=0:d=0.5,fade=t=out:st=3.7:d=0.7"
    )
    run([FF, "-y", *src(BG), "-t", f"{dur}", "-an", "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p", out])


def outro(out):
    dur = 3.8
    vf = (
        f"hflip,scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.30:saturation=1.08,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.48:t=fill,"
        f"drawtext=fontfile={FB}:text='Funoos':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.7),86+26*(t/0.7),112)':x=(w-text_w)/2:y=h*0.38"
        ":alpha='if(lt(t,0.15),0,if(lt(t,0.7),(t-0.15)/0.55,1))':shadowcolor=black@0.5:shadowx=0:shadowy=4,"
        f"drawtext=fontfile={FR}:text='github.com/SalehMohammadrezaei/Funoos':fontcolor=0xe6ecf9:fontsize=40"
        ":x=(w-text_w)/2:y='h*0.54+22*(1-min(max((t-0.7)/0.6,0),1))':alpha='if(lt(t,0.7),0,if(lt(t,1.3),(t-0.7)/0.6,1))',"
        f"drawtext=fontfile={FR}:text='free & open source · made by Saleh Mohammadrezaei':fontcolor=0x8493ad:fontsize=22"
        ":x=(w-text_w)/2:y=h*0.62:alpha='if(lt(t,1.3),0,if(lt(t,1.9),(t-1.3)/0.6,1))',"
        "fade=t=in:st=0:d=0.5,fade=t=out:st=3.05:d=0.7"
    )
    run([FF, "-y", *src(BG), "-t", f"{dur}", "-an", "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "15", "-preset", "medium", "-pix_fmt", "yuv420p", out])


# ---------- scene-library tile wall: every scene shown fully (blurred-fill tiles) ----------
def build_mosaic(keys, out, dur):
    cols, rows = 6, 5; tw, th = W // cols, H // rows
    logo = os.path.join(TMP, "logo_tile.png")
    img = Image.new("RGB", (tw, th), (10, 19, 34)); ImageDraw.Draw(img).text(
        (tw // 2, th // 2), "FUNOOS", font=ImageFont.truetype(FB, 38), fill=(138, 162, 255), anchor="mm")
    img.save(logo)
    n = len(keys) + 1
    coords = [(c * tw, r * th) for r in range(rows) for c in range(cols)][:n]
    inputs = []
    for k in keys: inputs += ["-stream_loop", "-1", "-i", os.path.join(GAL, k + ".mp4")]
    inputs += ["-loop", "1", "-framerate", str(FPS), "-i", logo]
    parts = []
    for i in range(len(keys)):
        parts.append(
            f"[{i}:v]fps={FPS},split[b{i}][f{i}];"
            f"[b{i}]scale={tw}:{th}:force_original_aspect_ratio=increase,crop={tw}:{th},gblur=sigma=6[bb{i}];"
            f"[f{i}]scale={tw-12}:{th-12}:force_original_aspect_ratio=decrease[ff{i}];"
            f"[bb{i}][ff{i}]overlay=(W-w)/2:(H-h)/2,setsar=1[s{i}]")
    parts.append(f"[{len(keys)}:v]scale={tw}:{th},setsar=1,fps={FPS}[s{len(keys)}]")
    layout = "|".join(f"{x}_{y}" for x, y in coords)
    parts.append("".join(f"[s{i}]" for i in range(n)) + f"xstack=inputs={n}:layout={layout}[wall]")
    post = (f"[wall]drawgrid=w={tw}:h={th}:t=3:color=0x0a1322,"
            f"zoompan=z='min(zoom+0.00035,1.045)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS},"
            f"drawtext=fontfile={FB}:text='29 SCENES TO EXPLORE':fontcolor=white:fontsize=36:x=96:y=60"
            ":alpha='if(lt(t,0.5),t/0.5,1)':shadowcolor=black@0.85:shadowx=0:shadowy=3,"
            f"drawtext=fontfile={FR}:text='six methods · one app · free & open source':fontcolor=0xcdd9f2:fontsize=27"
            f":x=(w-text_w)/2:y={H-64}:alpha='if(lt(t,0.6),t/0.6,1)':shadowcolor=black@0.9:shadowx=0:shadowy=3,"
            "fade=t=in:st=0:d=0.6[v]")
    run([FF, "-y", *inputs, "-filter_complex", ";".join(parts) + ";" + post, "-map", "[v]",
         "-t", f"{dur}", "-r", str(FPS), "-an", "-c:v", "libx264", "-crf", "16", "-preset", "medium",
         "-pix_fmt", "yuv420p", out])


# ---------- timeline ----------
print("building segments…")
segs, durs = [], []
def add(p, d): segs.append(p); durs.append(d)

it = os.path.join(TMP, "00.mp4"); intro(it); add(it, 4.4)
for i, (_, view, _, nm, _, _) in enumerate(VIEWSHOTS):
    o = os.path.join(TMP, f"1{i}.mp4")
    seg(dirs[nm], o, 2.9, view, SHOTSUB[view], "MANY WAYS TO SEE IT" if i == 0 else None); add(o, 2.9)
for i, (cm, short) in enumerate(RECOLOR):
    o = os.path.join(TMP, f"2{i}.mp4")
    seg(dirs["rc_" + short], o, 2.2, short, "Kelvin–Helmholtz · recolour live",
        "RECOLOR INSTANTLY" if i == 0 else None); add(o, 2.2)
print("building tile wall…")
mo = os.path.join(TMP, "80.mp4"); build_mosaic(MOSAIC, mo, 7.5); add(mo, 7.5)
ot = os.path.join(TMP, "99.mp4"); outro(ot); add(ot, 3.8)

print("crossfading -> final…")
TRANS = ["fade"] + ["dissolve"] * (len(segs) - 2) + ["fadeblack"]
inputs = []
for s in segs: inputs += ["-i", s]
fc = []; prev = "0:v"; off = 0.0
for k in range(1, len(segs)):
    off += durs[k - 1] - TR
    fc.append(f"[{prev}][{k}:v]xfade=transition={TRANS[k-1]}:duration={TR}:offset={off:.3f}[v{k}]"); prev = f"v{k}"
out_mp4 = os.path.join(ROOT, "funoos_promo.mp4")
run([FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{prev}]",
     "-c:v", "libx264", "-crf", "16", "-preset", "slow", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4])
total = sum(durs) - TR * (len(segs) - 1)
print(f"DONE -> {out_mp4}  ({W}x{H}, ~{total:.0f}s, {os.path.getsize(out_mp4)//1024} KB)")
