"""FlowZoo engine: run any exhibit and return rendered RGB frames.

This is the shared backend for both the command-line demos and the interactive
Studio GUI. Each exhibit is described by a parameter spec (so a GUI can build
its controls generically) and a runner that returns (frames, info_text).

Frames are HxWx3 uint8 arrays; the GUI plays them and can export GIF/MP4.
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import render, geometry

ROOT = Path(__file__).resolve().parents[1]
SOLVERS = ROOT / "solvers"


def _ensure(binpath):
    if not Path(binpath).exists():
        subprocess.run(["make", "-C", str(Path(binpath).parent)], check=True)


def _read_vel(d, i, nx, ny):
    buf = np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32)
    return buf[: nx * ny].reshape(ny, nx), buf[nx * ny :].reshape(ny, nx)


def _read_scalar(d, i, nx, ny):
    return np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx)


def _frames_count(d):
    return int([l.split()[1] for l in (Path(d) / "meta.txt").read_text().splitlines()
                if l.startswith("nframes")][0])


# ---------- runners ----------
def _run_lbm_text(p, progress, tmp):
    nx, ny = int(640 * p["scale"]), int(230 * p["scale"])
    Re = float(p["reynolds"]); U = 0.08; tau = 0.5 + 3 * (U * (ny * 0.5) / Re)
    steps = {"short": 22000, "medium": 40000, "long": 60000}[p["duration"]]
    _ensure(SOLVERS / "lbm" / "lbm2d")
    mask = geometry.text(nx, ny, p["text"], font_frac=0.34, x_frac=0.28, max_w_frac=0.5)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    progress(f"solving LBM {nx}x{ny}, {steps} steps...")
    subprocess.run([str(SOLVERS / "lbm" / "lbm2d"), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(steps // 120),
                    "--out", tmp, "--probe_x", str(int(nx * 0.6)), "--probe_y", str(ny // 2)],
                   check=True)
    n = _frames_count(tmp)
    use = range(n // 5, n, max(1, (n - n // 5) // 90))
    vort = [render.vorticity(*_read_vel(tmp, i, nx, ny)) for i in use]
    vmax = np.percentile(np.abs(vort[-1]), 99.0)
    frames = [render.field_to_rgb(v, render.FLOWZOO_CURL, -vmax, vmax,
                                  mask=mask, mask_color=render.SOLID, upscale=1) for v in vort]
    return frames, f"text='{p['text']}'  Re={Re:.0f}  {nx}x{ny}"


def _run_ns(mode, p, progress, tmp):
    nx, ny = int(280 * p["scale"]), int(440 * p["scale"])
    steps = {"short": 2600, "medium": 4200, "long": 6000}[p["duration"]]
    _ensure(SOLVERS / "incompressible" / "ins2d")
    args = [str(SOLVERS / "incompressible" / "ins2d"), "--mode", mode,
            "--nx", str(nx), "--ny", str(ny), "--steps", str(steps),
            "--save_every", str(steps // 110), "--out", tmp]
    if mode == "smoke":
        args += ["--buoy", "2.5e-3", "--conf", "8", "--visc", "8e-5"]
        cmap, vlim, gamma = render.FLOWZOO_EMBER, (0.0, 0.85), 0.85
    else:
        args += ["--grav", "1.2e-3", "--conf", "0", "--visc", "1.5e-4", "--iters", "80"]
        cmap, vlim, gamma = render.FLOWZOO_RT, (0.0, 1.0), 1.0
    progress(f"solving NS ({mode}) {nx}x{ny}, {steps} steps...")
    subprocess.run(args, check=True)
    n = _frames_count(tmp); skip = max(1, n // 100)
    frames = [render.field_to_rgb(_read_scalar(tmp, i, nx, ny), cmap, *vlim,
                                  upscale=1, gamma=gamma) for i in range(0, n, skip)]
    return frames, f"{mode}  {nx}x{ny}  {steps} steps"


def _run_euler(mode, p, progress, tmp):
    if mode == "blast":
        nx = ny = int(420 * p["scale"]); tend = 70
    else:
        nx, ny = int(640 * p["scale"]), int(320 * p["scale"]); tend = 230
    _ensure(SOLVERS / "compressible" / "euler2d")
    progress(f"solving Euler ({mode}) {nx}x{ny}...")
    subprocess.run([str(SOLVERS / "compressible" / "euler2d"), "--mode", mode,
                    "--nx", str(nx), "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4",
                    "--steps", "200000", "--save_every", "12", "--out", tmp], check=True)
    n = _frames_count(tmp); skip = max(1, n // 100)
    frames = []
    for i in range(0, n, skip):
        sch = render.schlieren(_read_scalar(tmp, i, nx, ny))
        frames.append(render.field_to_rgb(sch, render.FLOWZOO_EMBER, 0.0,
                                          np.percentile(sch, 99.5) + 1e-6, upscale=1, gamma=0.7))
    return frames, f"{mode}  {nx}x{ny}"


def _run_spectral(p, progress, tmp):
    from .spectral import Spectral2D, double_shear_layer
    n = int(256 * p["scale"]); nu = 8e-5
    steps = {"short": 1800, "medium": 2800, "long": 3600}[p["duration"]]
    sim = Spectral2D(n=n, nu=nu); wh = double_shear_layer(n); dt = 0.4 * (2 * np.pi / n)
    progress(f"spectral {n}x{n}, {steps} steps...")
    frames = []; vlim = None
    for s in range(steps + 1):
        if s % max(1, steps // 100) == 0:
            w = sim.vorticity(wh)
            if vlim is None: vlim = np.percentile(np.abs(w), 99.0)
            frames.append(render.field_to_rgb(w, render.FLOWZOO_CURL, -vlim, vlim, upscale=1))
        wh = sim.step(wh, dt)
    return frames, f"Kelvin-Helmholtz  {n}x{n}"


_DUR = {"name": "duration", "type": "choice", "choices": ["short", "medium", "long"],
        "default": "medium"}
_SCALE = {"name": "scale", "type": "float", "default": 1.0, "min": 0.4, "max": 1.6}

EXHIBITS = {
    "Flow around your name": {
        "params": [{"name": "text", "type": "str", "default": "FlowZoo"},
                   {"name": "reynolds", "type": "float", "default": 600, "min": 150, "max": 1500},
                   _SCALE, _DUR],
        "run": lambda p, pr, t: _run_lbm_text(p, pr, t)},
    "Smoke plume": {"params": [_SCALE, _DUR],
                    "run": lambda p, pr, t: _run_ns("smoke", p, pr, t)},
    "Rayleigh-Taylor": {"params": [_SCALE, _DUR],
                        "run": lambda p, pr, t: _run_ns("rt", p, pr, t)},
    "Explosion": {"params": [_SCALE], "run": lambda p, pr, t: _run_euler("blast", p, pr, t)},
    "Shock-bubble": {"params": [_SCALE], "run": lambda p, pr, t: _run_euler("bubble", p, pr, t)},
    "Kelvin-Helmholtz": {"params": [_SCALE, _DUR],
                         "run": lambda p, pr, t: _run_spectral(p, pr, t)},
}


def run_exhibit(name, params, progress=lambda s: None):
    """Run an exhibit; return (frames:list[HxWx3 uint8], info:str)."""
    spec = EXHIBITS[name]
    full = {q["name"]: q["default"] for q in spec["params"]}
    full.update(params or {})
    with tempfile.TemporaryDirectory() as tmp:
        return spec["run"](full, progress, tmp)
