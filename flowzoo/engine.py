"""FlowZoo engine: run any exhibit and return rendered RGB frames.

Shared backend for the command-line demos and the Studio GUI. Each exhibit
exposes a parameter spec (with help text, so a GUI can build labelled controls
with "?" tips) and a runner that returns (frames, info_text).

Frames are HxWx3 uint8 arrays; the GUI plays them and can export GIF/MP4.
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import render, geometry

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
SOLVERS = _BASE / "solvers"
EXE = ".exe" if sys.platform.startswith("win") else ""


def _bin(d, name):
    return SOLVERS / d / (name + EXE)


def _ensure(binpath):
    if Path(binpath).exists():
        return
    if sys.platform.startswith("win") or getattr(sys, "frozen", False):
        raise FileNotFoundError(
            f"solver not found: {binpath}. On Windows, build the solvers first "
            f"(see docs/windows_build.md).")
    subprocess.run(["make", "-C", str(Path(binpath).parent)], check=True)


def _read_vel(d, i, nx, ny):
    b = np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32)
    return b[: nx * ny].reshape(ny, nx), b[nx * ny:].reshape(ny, nx)


def _read_scalar(d, i, nx, ny):
    return np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx)


def _nframes(d):
    return int([l.split()[1] for l in (Path(d) / "meta.txt").read_text().splitlines()
                if l.startswith("nframes")][0])


# resolution / duration multipliers
RES = {"Low (fast)": 0.6, "Medium": 1.0, "High": 1.35, "Ultra (slow)": 1.8}
DUR = {"Quick": 0.5, "Short": 0.75, "Medium": 1.0, "Long": 1.5, "Epic": 2.2}


def _cmap(p, default):
    return render.COLORMAPS.get(p.get("colormap", default), default)


def _res(p):
    return RES.get(p.get("resolution", "Medium"), 1.0)


def _dur(p):
    return DUR.get(p.get("duration", "Medium"), 1.0)


# ---------- choice-param builders (with help text) ----------
def _P_RES(help="Grid resolution. Higher = sharper detail but slower to run."):
    return {"name": "resolution", "label": "Resolution", "type": "choice",
            "choices": list(RES), "default": "Medium", "help": help}


def _P_DUR(help="How long to simulate. Longer captures more of the evolution."):
    return {"name": "duration", "label": "Duration", "type": "choice",
            "choices": list(DUR), "default": "Medium", "help": help}


def _P_CMAP(default="Curl (cyan–amber)"):
    return {"name": "colormap", "label": "Color palette", "type": "choice",
            "choices": list(render.COLORMAPS), "default": default,
            "help": "Color scheme used to paint the field."}


# ---------- runners ----------
def _run_vortex(p, pr, tmp):
    s = _res(p); nx, ny = int(820 * s), int(260 * s)
    D = int(34 * s); Re = float(p["reynolds"]); U = 0.08
    tau = 0.5 + 3 * (U * D / Re)
    steps = int(42000 * _dur(p))
    _ensure(_bin("lbm", "lbm2d"))
    mask = geometry.cylinder(nx, ny, nx // 4, ny // 2 + 2, D / 2)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    pr(f"solving LBM cylinder {nx}x{ny}, Re={Re:.0f}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(nx // 4 + 3 * D), "--probe_y", str(ny // 2)],
                   check=True)
    n = _nframes(tmp); cm = _cmap(p, render.FLOWZOO_CURL)
    use = range(n // 5, n, max(1, (n - n // 5) // 90))
    vort = [render.vorticity(*_read_vel(tmp, i, nx, ny)) for i in use]
    vmax = np.percentile(np.abs(vort[-1]), 99.5)
    return ([render.field_to_rgb(v, cm, -vmax, vmax, mask=mask,
                                 mask_color=render.SOLID, upscale=1) for v in vort],
            f"Kármán vortex street  Re={Re:.0f}  {nx}x{ny}")


def _run_lbm_text(p, pr, tmp):
    s = _res(p); nx, ny = int(900 * s), int(330 * s)
    Re = float(p["reynolds"]); U = 0.08; tau = 0.5 + 3 * (U * (ny * 0.5) / Re)
    steps = int(46000 * _dur(p))
    _ensure(_bin("lbm", "lbm2d"))
    mask = geometry.text(nx, ny, p["text"], font_frac=0.34, x_frac=0.28, max_w_frac=0.5)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    pr(f"solving LBM text '{p['text']}' {nx}x{ny}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(int(nx * 0.6)), "--probe_y", str(ny // 2)],
                   check=True)
    n = _nframes(tmp); cm = _cmap(p, render.FLOWZOO_CURL)
    use = range(n // 5, n, max(1, (n - n // 5) // 90))
    vort = [render.vorticity(*_read_vel(tmp, i, nx, ny)) for i in use]
    vmax = np.percentile(np.abs(vort[-1]), 99.0)
    return ([render.field_to_rgb(v, cm, -vmax, vmax, mask=mask,
                                 mask_color=render.SOLID, upscale=1) for v in vort],
            f"flow around '{p['text']}'  Re={Re:.0f}  {nx}x{ny}")


def _run_ns(mode, p, pr, tmp):
    s = _res(p); nx, ny = int(280 * s), int(440 * s)
    steps = int(4800 * _dur(p))
    _ensure(_bin("incompressible", "ins2d"))
    args = [str(_bin("incompressible", "ins2d")), "--mode", mode, "--nx", str(nx),
            "--ny", str(ny), "--steps", str(steps),
            "--save_every", str(max(1, steps // 110)), "--out", tmp,
            "--visc", str(p["viscosity"])]
    if mode == "smoke":
        args += ["--buoy", str(p["buoyancy"]), "--conf", str(p["confinement"])]
        cm, vlim, g = _cmap(p, render.FLOWZOO_EMBER), (0.0, 0.85), 0.85
    else:
        args += ["--grav", str(p["gravity"]), "--conf", "0", "--iters", "80"]
        cm, vlim, g = _cmap(p, render.FLOWZOO_RT), (0.0, 1.0), 1.0
    pr(f"solving Navier–Stokes ({mode}) {nx}x{ny}, {steps} steps…")
    subprocess.run(args, check=True)
    n = _nframes(tmp); skip = max(1, n // 100)
    return ([render.field_to_rgb(_read_scalar(tmp, i, nx, ny), cm, *vlim, upscale=1, gamma=g)
             for i in range(0, n, skip)], f"{mode}  {nx}x{ny}  {steps} steps")


def _run_euler(mode, p, pr, tmp):
    s = _res(p)
    if mode == "blast":
        nx = ny = int(420 * s); tend = 70
    else:
        nx, ny = int(620 * s), int(320 * s); tend = 230
    _ensure(_bin("compressible", "euler2d"))
    pr(f"solving compressible Euler ({mode}) {nx}x{ny}…")
    subprocess.run([str(_bin("compressible", "euler2d")), "--mode", mode, "--nx", str(nx),
                    "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4",
                    "--steps", "200000", "--save_every", "12", "--out", tmp], check=True)
    n = _nframes(tmp); skip = max(1, n // 100); cm = _cmap(p, render.FLOWZOO_EMBER)
    idx = list(range(0, n, skip))
    frames = []
    # explosion debris: kinematic glowing particles flung radially from the centre
    deb = int(p.get("debris", 0))
    if deb and mode == "blast":
        rng = np.random.default_rng(7)
        ang = rng.uniform(0, 2 * np.pi, deb)
        spd = rng.uniform(0.45, 1.0, deb) * 0.5 * min(nx, ny)
        cx, cy = nx / 2, ny / 2
    for fi, i in enumerate(idx):
        sch = render.schlieren(_read_scalar(tmp, i, nx, ny))
        img = render.field_to_rgb(sch, cm, 0.0, np.percentile(sch, 99.5) + 1e-6,
                                  upscale=1, gamma=0.7)
        if deb and mode == "blast":
            tau = fi / max(1, len(idx) - 1)
            r = spd * tau
            px = cx + r * np.cos(ang); py = cy + r * np.sin(ang)
            iy = ny - 1 - py                       # field_to_rgb flips y
            keep = (px > 1) & (px < nx - 1) & (iy > 1) & (iy < ny - 1)
            img = render.overlay_particles(img, px[keep], iy[keep],
                                           sizes=np.full(keep.sum(), 1.6))
        frames.append(img)
    return frames, f"{mode}  {nx}x{ny}"


def _run_dam(p, pr, tmp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = _res(p); dp = 0.05 / s; a, H, Lx, Ly = 1.0, 2.0, 5.0, 3.2
    _ensure(_bin("sph", "sph2d"))
    pr(f"solving SPH dam break (dp={dp:.3f})…")
    subprocess.run([str(_bin("sph", "sph2d")), "--a", str(a), "--H", str(H), "--Lx", str(Lx),
                    "--Ly", str(Ly), "--dp", str(dp), "--tend", str(1.6 * _dur(p)),
                    "--save_every", "60", "--out", tmp], check=True)
    n = _nframes(tmp); skip = max(1, n // 100); cm = _cmap(p, render.FLOWZOO_WATER)
    vmax = 1.2 * np.sqrt(2 * 9.81 * H); frames = []
    for i in range(0, n, skip):
        d = np.fromfile(Path(tmp) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3)
        fig = plt.figure(figsize=(6.4, 6.4 * Ly / Lx), dpi=110)
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(render.INK)
        fig.patch.set_facecolor(render.INK)
        ax.scatter(d[:, 0], d[:, 1], c=np.clip(d[:, 2] / vmax, 0, 1), cmap=cm,
                   s=7, edgecolors="none")
        ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
        fig.canvas.draw(); w, h = fig.canvas.get_width_height()
        frames.append(np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
                      .reshape(h, w, 4)[..., :3].copy())
        plt.close(fig)
    return frames, f"dam break  {len(frames)} frames"


def _run_spectral(p, pr, tmp):
    from .spectral import Spectral2D, double_shear_layer
    s = _res(p); n = int(256 * s)
    steps = int(2800 * _dur(p)); nu = float(p["viscosity"])
    sim = Spectral2D(n=n, nu=nu); wh = double_shear_layer(n); dt = 0.4 * (2 * np.pi / n)
    cm = _cmap(p, render.FLOWZOO_CURL)
    pr(f"spectral {n}x{n}, ν={nu:.1e}, {steps} steps…")
    frames = []; vlim = None
    for st in range(steps + 1):
        if st % max(1, steps // 100) == 0:
            w = sim.vorticity(wh)
            if vlim is None:
                vlim = np.percentile(np.abs(w), 99.0)
            frames.append(render.field_to_rgb(w, cm, -vlim, vlim, upscale=1))
        wh = sim.step(wh, dt)
    return frames, f"Kelvin–Helmholtz  {n}x{n}  ν={nu:.1e}"


# help strings
_H = {
    "Re": "Reynolds number Re = U·D/ν (inertia ÷ viscosity). Low → smooth steady "
          "flow; high → vortex shedding and turbulence.",
    "visc": "Kinematic viscosity ν — how 'thick' the fluid is. Lower → finer, more "
            "chaotic structures; higher → smoother, damped flow.",
    "buoy": "Buoyancy strength — how forcefully the hot, dyed fluid rises. Higher → "
            "a faster, more violent plume.",
    "conf": "Vorticity confinement — re-injects small-scale swirl lost to numerical "
            "diffusion. Higher → curlier, more detailed smoke.",
    "grav": "Gravity driving the instability. Higher → faster fingering / collapse.",
    "debris": "Number of glowing debris particles flung out by the blast (visual only).",
}

EXHIBITS = {
    "Vortex street (LBM)": {
        "params": [{"name": "reynolds", "label": "Reynolds number", "type": "float",
                    "default": 160, "min": 60, "max": 1000, "help": _H["Re"]},
                   _P_RES(), _P_DUR(), _P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_vortex(p, pr, t)},
    "Flow around your name (LBM)": {
        "params": [{"name": "text", "label": "Text", "type": "str", "default": "FlowZoo",
                    "help": "The word(s) the flow sheds vortices off. Short = crispest."},
                   {"name": "reynolds", "label": "Reynolds number", "type": "float",
                    "default": 600, "min": 150, "max": 1500, "help": _H["Re"]},
                   _P_RES(), _P_DUR(), _P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_lbm_text(p, pr, t)},
    "Smoke plume (Navier–Stokes)": {
        "params": [{"name": "buoyancy", "label": "Buoyancy", "type": "float",
                    "default": 2.5e-3, "min": 5e-4, "max": 6e-3, "help": _H["buoy"]},
                   {"name": "confinement", "label": "Vorticity confinement", "type": "float",
                    "default": 8, "min": 0, "max": 20, "help": _H["conf"]},
                   {"name": "viscosity", "label": "Viscosity", "type": "float",
                    "default": 8e-5, "min": 0, "max": 5e-4, "help": _H["visc"]},
                   _P_RES(), _P_DUR(), _P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_ns("smoke", p, pr, t)},
    "Rayleigh–Taylor (Navier–Stokes)": {
        "params": [{"name": "gravity", "label": "Gravity", "type": "float",
                    "default": 1.2e-3, "min": 4e-4, "max": 3e-3, "help": _H["grav"]},
                   {"name": "viscosity", "label": "Viscosity", "type": "float",
                    "default": 1.5e-4, "min": 3e-5, "max": 5e-4, "help": _H["visc"]},
                   _P_RES(), _P_DUR(), _P_CMAP("Hot / Cold")],
        "run": lambda p, pr, t: _run_ns("rt", p, pr, t)},
    "Explosion (Compressible)": {
        "params": [{"name": "debris", "label": "Debris particles", "type": "float",
                    "default": 160, "min": 0, "max": 600, "help": _H["debris"]},
                   _P_RES(), _P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_euler("blast", p, pr, t)},
    "Shock–bubble (Compressible)": {
        "params": [_P_RES(), _P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_euler("bubble", p, pr, t)},
    "Dam break (SPH)": {
        "params": [_P_RES("Particle resolution. Higher = more particles, finer splash."),
                   _P_DUR(), _P_CMAP("Ocean (water)")],
        "run": lambda p, pr, t: _run_dam(p, pr, t)},
    "Kelvin–Helmholtz (Spectral)": {
        "params": [{"name": "viscosity", "label": "Viscosity", "type": "float",
                    "default": 8e-5, "min": 1e-5, "max": 4e-4, "help": _H["visc"]},
                   _P_RES(), _P_DUR(), _P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_spectral(p, pr, t)},
}


def run_exhibit(name, params, progress=lambda s: None):
    """Run an exhibit; return (frames:list[HxWx3 uint8], info:str)."""
    spec = EXHIBITS[name]
    full = {q["name"]: q["default"] for q in spec["params"]}
    full.update(params or {})
    with tempfile.TemporaryDirectory() as tmp:
        return spec["run"](full, progress, tmp)
