"""Cinematic product film for Funoos -> funoos_promo.mp4.

Tells what the app *does*: run one simulation, then flip it live between views
(Speed / Vorticity / Streamlines), recolor across palettes, then explore the
scene library.  Footage is rendered live from a single solve via the engine
(Result.render(view, colormap)); assembly + grading (bloom, vignette, scope
bars, slow dissolves, kinetic type) is ffmpeg.  Run: ./.venv/bin/python make_promo.py
"""
import os, subprocess, tempfile, numpy as np
import flowzoo.engine as E, flowzoo.render as R

FF = "/usr/bin/ffmpeg"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FR = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
W, H, FPS, TR = 1280, 720, 30, 0.7
ROOT = os.path.dirname(os.path.abspath(__file__)); GAL = os.path.join(ROOT, "results", "gallery")
TMP = tempfile.mkdtemp(prefix="promo_")
BAR = 58  # cinemascope bar height


def run(a): subprocess.run(a, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT)
def esc(p): return p.replace(":", "\\:")  # for textfile paths (none needed here)


def raw_clip(frames, name):
    p = os.path.join(TMP, name + "_raw.mp4")
    R.save_mp4([np.asarray(f) for f in frames], p, fps=28)
    return p


# ---------- generate footage from ONE solve ----------
print("solving Wind Tunnel (vortex street)…")
res = E.solve_exhibit("Wind Tunnel", {"resolution": "Medium", "duration": 1.3})
print("rendering views + recolors…")
clips = {
    "speed":  raw_clip(res.render("Speed", "Ocean (water)"), "speed"),
    "vort":   raw_clip(res.render("Vorticity", "Curl (cyan–amber)"), "vort"),
    "stream": raw_clip(res.render("Streamlines", "Ember (fire)"), "stream"),
}
RECOLOR = [("Curl (cyan–amber)", "Curl"), ("Inferno", "Inferno"), ("Twilight", "Twilight"), ("Turbo", "Turbo")]
for cm, short in RECOLOR:
    clips["rc_" + short] = raw_clip(res.render("Vorticity", cm), "rc_" + short)


# ---------- one normalized, graded, labelled segment ----------
def seg(src, out, dur, chip, sub, chapter=None, crop_cbar=False, loop=False, zoom=True):
    nf = os.path.join(TMP, os.path.basename(out) + "_n.txt"); open(nf, "w").write(chip)
    mf = os.path.join(TMP, os.path.basename(out) + "_m.txt"); open(mf, "w").write(sub)
    chain = []
    if crop_cbar: chain.append("crop=iw*0.88:ih:0:0")
    chain += [f"scale={W}:{H}:force_original_aspect_ratio=decrease",
              f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=0x070d18", "setsar=1", f"fps={FPS}"]
    if zoom:
        chain.append(f"zoompan=z='min(zoom+0.0005,1.07)':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={W}x{H}:fps={FPS}")
    chain.append("vignette")
    # lower-third (kept above the bottom scope bar at y=662)
    chain.append(f"drawbox=x=0:y=500:w={W}:h=162:color=0x050a14@0.55:t=fill")
    chain.append(f"drawbox=x=60:y=520:w=5:h=66:color=0x8aa2ff@0.95:t=fill")
    chain.append(f"drawtext=fontfile={FB}:textfile={nf}:fontcolor=white:fontsize=44"
                 ":x='84-46*(1-min(max(t/0.5,0),1))':y=520:alpha='if(lt(t,0.5),t/0.5,1)':borderw=2:bordercolor=black@0.5")
    chain.append(f"drawtext=fontfile={FR}:textfile={mf}:fontcolor=0x9db4f0:fontsize=24"
                 ":x='84-46*(1-min(max((t-0.12)/0.5,0),1))':y=584"
                 ":alpha='if(lt(t,0.12),0,if(lt(t,0.62),(t-0.12)/0.5,1))'")
    if chapter:
        chain.append(f"drawtext=fontfile={FB}:text='{chapter}':fontcolor=0x8aa2ff:fontsize=22:x=64:y=78"
                     f":alpha='if(lt(t,0.4),t/0.4,if(lt(t,{dur-0.5:.2f}),1,({dur:.2f}-t)/0.5))'")
    vf = ",".join(chain)
    ins = ["-stream_loop", "-1"] if loop else []
    run([FF, "-y", *ins, "-i", src, "-t", f"{dur}", "-an", "-vf", vf, "-r", str(FPS),
         "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


# ---------- animated cinematic intro (streamlines backdrop) ----------
def intro(out):
    dur = 5.0
    vf = (
        f"crop=iw*0.88:ih:0:0,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.26:saturation=1.16,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.40:t=fill,"
        f"drawtext=fontfile={FB}:text='FUNOOS':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.9),58+80*(t/0.9),138)':x=(w-text_w)/2:y=(h-text_h)/2-22"
        ":alpha='if(lt(t,0.25),0,if(lt(t,0.9),(t-0.25)/0.65,1))':shadowcolor=black@0.55:shadowx=0:shadowy=3,"
        f"drawtext=fontfile={FR}:text='a fluid-dynamics studio you can watch'"
        ":fontcolor=0xe6ecf9:fontsize=27:x=(w-text_w)/2:y='h*0.605+24*(1-min(max((t-1.0)/0.7,0),1))'"
        ":alpha='if(lt(t,1.0),0,if(lt(t,1.7),(t-1.0)/0.7,1))',"
        f"drawtext=fontfile={FR}:text='run it · switch how you see it · recolor · measure'"
        ":fontcolor=0x8493ad:fontsize=15:x=(w-text_w)/2:y=h*0.675"
        ":alpha='if(lt(t,1.8),0,if(lt(t,2.5),(t-1.8)/0.7,1))',"
        "vignette,fade=t=in:st=0:d=0.5,fade=t=out:st=4.3:d=0.7"
    )
    run([FF, "-y", "-stream_loop", "-1", "-i", clips["stream"], "-t", f"{dur}", "-an", "-vf", vf,
         "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


def outro(out):
    dur = 3.8
    bg = "spec_decay" if os.path.exists(os.path.join(GAL, "spec_decay.mp4")) else "lbm_cylinder"
    vf = (
        f"crop=iw*0.85:ih:0:0,hflip,scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS},"
        "eq=brightness=-0.34:saturation=1.10,"
        f"drawbox=x=0:y=0:w={W}:h={H}:color=black@0.50:t=fill,"
        f"drawtext=fontfile={FB}:text='Funoos':fontcolor=0x8aa2ff"
        ":fontsize='if(lt(t,0.7),60+18*(t/0.7),78)':x=(w-text_w)/2:y=h*0.39"
        ":alpha='if(lt(t,0.15),0,if(lt(t,0.7),(t-0.15)/0.55,1))':shadowcolor=black@0.5:shadowx=0:shadowy=3,"
        f"drawtext=fontfile={FR}:text='github.com/SalehMohammadrezaei/Funoos':fontcolor=0xe6ecf9:fontsize=26"
        ":x=(w-text_w)/2:y='h*0.54+18*(1-min(max((t-0.7)/0.6,0),1))':alpha='if(lt(t,0.7),0,if(lt(t,1.3),(t-0.7)/0.6,1))',"
        f"drawtext=fontfile={FR}:text='free & open source · made by Saleh Mohammadrezaei':fontcolor=0x8493ad:fontsize=15"
        ":x=(w-text_w)/2:y=h*0.62:alpha='if(lt(t,1.3),0,if(lt(t,1.9),(t-1.3)/0.6,1))',"
        "vignette,fade=t=in:st=0:d=0.5,fade=t=out:st=3.05:d=0.7"
    )
    run([FF, "-y", "-stream_loop", "-1", "-i", os.path.join(GAL, bg + ".mp4"), "-t", f"{dur}", "-an",
         "-vf", vf, "-r", str(FPS), "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", out])


# ---------- build the timeline ----------
print("building segments…")
segs, durs = [], []
def add(p, d): segs.append(p); durs.append(d)

it = os.path.join(TMP, "00_intro.mp4"); intro(it); add(it, 5.0)

# Chapter 1 — same simulation, three live views (clean dissolves = the morph)
seg(clips["speed"],  os.path.join(TMP, "10.mp4"), 2.8, "Speed",       "one of several live views", chapter="SEE IT YOUR WAY", loop=True); add(os.path.join(TMP, "10.mp4"), 2.8)
seg(clips["vort"],   os.path.join(TMP, "11.mp4"), 2.8, "Vorticity",   "same run, switched live", loop=True);                            add(os.path.join(TMP, "11.mp4"), 2.8)
seg(clips["stream"], os.path.join(TMP, "12.mp4"), 3.4, "Streamlines", "same run, switched live", loop=True);                            add(os.path.join(TMP, "12.mp4"), 3.4)

# Chapter 2 — recolor across palettes
ch = "RECOLOR INSTANTLY"
for i, (cm, short) in enumerate(RECOLOR):
    o = os.path.join(TMP, f"2{i}.mp4")
    seg(clips["rc_" + short], o, 2.2, short, "11 palettes, one click", chapter=ch if i == 0 else None, loop=True)
    add(o, 2.2)

# Chapter 3 — explore the library
LIB = [("ns_flame", "Candle Flame", "Navier–Stokes"), ("euler_city", "Shockwave Hits a City", "Compressible Euler"),
       ("sph_dam", "Dam Break", "SPH"), ("rd_mitosis", "Turing Patterns", "Reaction–Diffusion"),
       ("porous_phi60", "Flow Through Rock", "permeability")]
for i, (k, n, m) in enumerate(LIB):
    o = os.path.join(TMP, f"3{i}.mp4")
    seg(os.path.join(GAL, k + ".mp4"), o, 2.6, n, m, chapter="29 SCENES TO EXPLORE" if i == 0 else None)
    add(o, 2.6)

ot = os.path.join(TMP, "99_outro.mp4"); outro(ot); add(ot, 3.8)

# ---------- crossfade ----------
print("crossfading…")
TRANS = ["fade", "dissolve", "dissolve", "dissolve", "dissolve", "dissolve", "dissolve",
         "smoothleft", "dissolve", "smoothup", "dissolve", "smoothleft", "fadeblack"]
inputs = []
for s in segs: inputs += ["-i", s]
fc = []; prev = "0:v"; off = 0.0
for k in range(1, len(segs)):
    off += durs[k - 1] - TR
    tr = TRANS[(k - 1) % len(TRANS)]
    lab = f"v{k}"
    fc.append(f"[{prev}][{k}:v]xfade=transition={tr}:duration={TR}:offset={off:.3f}[{lab}]")
    prev = lab
master = os.path.join(TMP, "master.mp4")
run([FF, "-y", *inputs, "-filter_complex", ";".join(fc), "-map", f"[{prev}]",
     "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", master])

# ---------- final cinematic grade: bloom + grade + vignette + scope bars ----------
print("grading…")
out_mp4 = os.path.join(ROOT, "funoos_promo.mp4")
grade = (
    "[0:v]split[a][b];[b]gblur=sigma=7[bl];"
    "[a][bl]blend=all_mode=screen:all_opacity=0.28,"
    "eq=contrast=1.06:saturation=1.10:brightness=-0.008,vignette,"
    f"drawbox=x=0:y=0:w={W}:h={BAR}:color=black:t=fill,"
    f"drawbox=x=0:y={H-BAR}:w={W}:h={BAR}:color=black:t=fill,format=yuv420p[v]"
)
run([FF, "-y", "-i", master, "-filter_complex", grade, "-map", "[v]",
     "-c:v", "libx264", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart", out_mp4])
total = sum(durs) - TR * (len(segs) - 1)
print(f"DONE -> {out_mp4}  (~{total:.0f}s, {os.path.getsize(out_mp4)//1024} KB)")
