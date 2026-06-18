"""FlowZoo engine: run any exhibit and return rendered RGB frames.

Shared backend for the demos and the Studio GUI. Each exhibit exposes a full
parameter spec (grouped, with help text and ranges, so a GUI can build labelled
controls with "?" tips) and a runner returning (frames, info_text).
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


def _ensure(b):
    if Path(b).exists():
        return
    if sys.platform.startswith("win") or getattr(sys, "frozen", False):
        raise FileNotFoundError(f"solver not found: {b}. Build it first "
                                f"(see docs/windows_build.md).")
    subprocess.run(["make", "-C", str(Path(b).parent)], check=True)


def _read_vel(d, i, nx, ny):
    b = np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32)
    return b[: nx * ny].reshape(ny, nx), b[nx * ny:].reshape(ny, nx)


def _read_scalar(d, i, nx, ny):
    return np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx)


def _nframes(d):
    return int([l.split()[1] for l in (Path(d) / "meta.txt").read_text().splitlines()
                if l.startswith("nframes")][0])


RES = {"Low (fast)": 0.6, "Medium": 1.0, "High": 1.35, "Ultra (slow)": 1.8}


def _cmap(p, default):
    return render.COLORMAPS.get(p.get("colormap", default), default)


def _res(p):
    return RES.get(p.get("resolution", "Medium"), 1.0)


def _durv(p):
    return float(p.get("duration", 1.0))


# ---------- reusable parameter descriptors ----------
def P_RES(help="Grid resolution. Higher = sharper detail but slower."):
    return {"name": "resolution", "label": "Resolution", "type": "choice",
            "choices": list(RES), "default": "Medium", "group": "Render", "help": help}


def P_DUR(help="Simulation length multiplier — set any value (1.0 = default)."):
    return {"name": "duration", "label": "Duration (×)", "type": "float", "default": 1.0,
            "min": 0.2, "max": 6.0, "group": "Render", "help": help}


def P_CMAP(default="Curl (cyan–amber)"):
    return {"name": "colormap", "label": "Color palette", "type": "choice",
            "choices": list(render.COLORMAPS), "default": default, "group": "Render",
            "help": "Color scheme used to paint the field."}


def _f(name, label, default, lo, hi, group, help):
    return {"name": name, "label": label, "type": "float", "default": default,
            "min": lo, "max": hi, "group": group, "help": help}


_H = {
    "Re": "Reynolds number Re = U·D/ν (inertia ÷ viscosity). Low → smooth steady flow; "
          "high → vortex shedding and turbulence.",
    "U": "Inlet flow speed (lattice units). Higher → higher Reynolds and a stronger wake; "
         "keep ≲ 0.15 for numerical stability.",
    "visc": "Kinematic viscosity ν — how 'thick' the fluid is. Lower → finer, more chaotic "
            "structures; higher → smoother, damped flow.",
    "buoy": "Buoyancy — how forcefully the hot, dyed fluid rises. Higher → a faster, more "
            "violent plume.",
    "conf": "Vorticity confinement — re-injects small-scale swirl lost to numerical "
            "diffusion. Higher → curlier, more detailed smoke.",
    "grav": "Gravity driving the instability. Higher → faster fingering / collapse.",
}


def _lbm_render(tmp, nx, ny, mask, p):
    """Render LBM velocity frames in the chosen view mode."""
    n = _nframes(tmp); view = p.get("view", "Vorticity")
    step = max(1, (n - n // 5) // (55 if view == "Streamlines" else 90))
    use = list(range(n // 5, n, step))
    if view == "Streamlines":
        cm = _cmap(p, render.FLOWZOO_EMBER)
        return [render.streamlines_rgb(*_read_vel(tmp, i, nx, ny), cmap=cm, mask=mask)
                for i in use]
    if view == "Speed":
        cm = _cmap(p, render.FLOWZOO_EMBER)
        sp = [render.speed(*_read_vel(tmp, i, nx, ny)) for i in use]
        vmax = np.percentile(sp[-1], 99.5) + 1e-12
        return [render.field_to_rgb(s, cm, 0, vmax, mask=mask, mask_color=render.SOLID,
                                    upscale=1) for s in sp]
    cm = _cmap(p, render.FLOWZOO_CURL)
    vort = [render.vorticity(*_read_vel(tmp, i, nx, ny)) for i in use]
    vmax = np.percentile(np.abs(vort[-1]), 99.0)
    return [render.field_to_rgb(w, cm, -vmax, vmax, mask=mask, mask_color=render.SOLID,
                                upscale=1) for w in vort]


_P_VIEW = {"name": "view", "label": "Visualization", "type": "choice",
           "choices": ["Vorticity", "Speed", "Streamlines"], "default": "Vorticity",
           "group": "Render", "help": "What to draw: vorticity (spin), speed magnitude, "
           "or flow streamlines."}
_P_VIEW_C = {"name": "view", "label": "Visualization", "type": "choice",
             "choices": ["Schlieren", "Density"], "default": "Schlieren", "group": "Render",
             "help": "Schlieren lights up shock fronts (|∇ρ|); Density shows raw density."}


# ---------- runners ----------
def _run_vortex(p, pr, tmp):
    s = _res(p); nx, ny = int(820 * s), int(260 * s)
    D = int(p["diameter"] * s); Re = float(p["reynolds"]); U = float(p["speed"])
    tau = 0.5 + 3 * (U * D / Re); steps = int(42000 * _durv(p))
    _ensure(_bin("lbm", "lbm2d"))
    mask = geometry.cylinder(nx, ny, nx // 4, ny // 2 + 2, D / 2)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    pr(f"LBM cylinder {nx}×{ny}, Re={Re:.0f}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(nx // 4 + 3 * D), "--probe_y", str(ny // 2)],
                   check=True)
    return (_lbm_render(tmp, nx, ny, mask, p),
            f"vortex street  Re={Re:.0f}  {nx}×{ny}  ({p.get('view', 'Vorticity')})")


def _run_lbm_text(p, pr, tmp):
    s = _res(p); nx, ny = int(900 * s), int(330 * s)
    Re = float(p["reynolds"]); U = float(p["speed"]); tau = 0.5 + 3 * (U * (ny * 0.5) / Re)
    steps = int(46000 * _durv(p))
    _ensure(_bin("lbm", "lbm2d"))
    mask = geometry.text(nx, ny, p["text"], font_frac=float(p["font"]), x_frac=0.28, max_w_frac=0.5)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    pr(f"LBM text '{p['text']}' {nx}×{ny}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(int(nx * 0.6)), "--probe_y", str(ny // 2)],
                   check=True)
    return (_lbm_render(tmp, nx, ny, mask, p),
            f"flow around '{p['text']}'  {nx}×{ny}  ({p.get('view', 'Vorticity')})")


def _run_ns(mode, p, pr, tmp):
    s = _res(p); nx, ny = int(280 * s), int(440 * s); steps = int(4800 * _durv(p))
    _ensure(_bin("incompressible", "ins2d"))
    args = [str(_bin("incompressible", "ins2d")), "--mode", mode, "--nx", str(nx),
            "--ny", str(ny), "--steps", str(steps), "--save_every", str(max(1, steps // 110)),
            "--out", tmp, "--visc", str(p["viscosity"])]
    if mode == "smoke":
        args += ["--buoy", str(p["buoyancy"]), "--conf", str(p["confinement"]),
                 "--srcw", str(p["source"])]
        cm, vlim, g = _cmap(p, render.FLOWZOO_EMBER), (0.0, 0.85), 0.85
    else:
        args += ["--grav", str(p["gravity"]), "--pert", str(p["perturbation"]),
                 "--conf", "0", "--iters", "80"]
        cm, vlim, g = _cmap(p, render.FLOWZOO_RT), (0.0, 1.0), 1.0
    pr(f"Navier–Stokes ({mode}) {nx}×{ny}, {steps} steps…")
    subprocess.run(args, check=True)
    n = _nframes(tmp); skip = max(1, n // 100)
    return ([render.field_to_rgb(_read_scalar(tmp, i, nx, ny), cm, *vlim, upscale=1, gamma=g)
             for i in range(0, n, skip)], f"{mode}  {nx}×{ny}  {steps} steps")


def _run_euler(mode, p, pr, tmp):
    s = _res(p)
    if mode == "blast":
        nx = ny = int(420 * s); tend = 70 * _durv(p)
        extra = ["--p0", str(p["pressure"]), "--radius", str(p["charge"])]
    else:
        nx, ny = int(620 * s), int(320 * s); tend = 230 * _durv(p)
        extra = ["--bubr", str(p["bubble"])]
    _ensure(_bin("compressible", "euler2d"))
    pr(f"compressible Euler ({mode}) {nx}×{ny}…")
    subprocess.run([str(_bin("compressible", "euler2d")), "--mode", mode, "--nx", str(nx),
                    "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4", "--steps", "200000",
                    "--save_every", "12", "--out", tmp] + extra, check=True)
    n = _nframes(tmp); skip = max(1, n // 100); cm = _cmap(p, render.FLOWZOO_EMBER)
    idx = list(range(0, n, skip)); frames = []
    deb = int(p.get("debris", 0))
    if deb and mode == "blast":                # debris scattered across the WHOLE domain,
        rng = np.random.default_rng(7)         # then swept outward as the blast wave passes
        bx = rng.uniform(0, nx, deb); by = rng.uniform(0, ny, deb)
        cx, cy = nx / 2, ny / 2
        dist = np.hypot(bx - cx, by - cy) + 1e-6
        ang = np.arctan2(by - cy, bx - cx)
        push = rng.uniform(0.5, 1.0, deb); Rmax = 0.75 * np.hypot(nx, ny) / 2
    density_view = p.get("view", "Schlieren") == "Density"
    for fi, i in enumerate(idx):
        rho = _read_scalar(tmp, i, nx, ny)
        if density_view:
            img = render.field_to_rgb(rho, cm, np.percentile(rho, 1),
                                      np.percentile(rho, 99.5) + 1e-6, upscale=1)
        else:
            sch = render.schlieren(rho)
            img = render.field_to_rgb(sch, cm, 0.0, np.percentile(sch, 99.5) + 1e-6,
                                      upscale=1, gamma=0.7)
        if deb and mode == "blast":
            tau = fi / max(1, len(idx) - 1)
            Rs = Rmax * tau * 1.25
            passed = Rs > dist
            disp = np.where(passed, (Rs - dist) * push * 0.9, 0.0)
            px = bx + np.cos(ang) * disp; py = by + np.sin(ang) * disp
            iy = ny - 1 - py
            keep = (px > 1) & (px < nx - 1) & (iy > 1) & (iy < ny - 1)
            sz = np.where(passed[keep], 1.9, 1.0)
            img = render.overlay_particles(img, px[keep], iy[keep], sz)
        frames.append(img)
    return frames, f"{mode}  {nx}×{ny}"


def _run_dam(p, pr, tmp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    a, H, Lx, Ly = float(p["width"]), float(p["height"]), 5.0, 3.2
    npart = max(400, float(p["particles"]))
    dp = float(np.clip(np.sqrt(a * H / npart), 0.014, 0.08))
    _ensure(_bin("sph", "sph2d"))
    pr(f"SPH dam break (~{int(a * H / dp / dp)} particles)…")
    subprocess.run([str(_bin("sph", "sph2d")), "--a", str(a), "--H", str(H), "--Lx", str(Lx),
                    "--Ly", str(Ly), "--dp", str(dp), "--g", str(p["gravity"]),
                    "--tend", str(1.6 * _durv(p)), "--save_every", "60", "--out", tmp], check=True)
    n = _nframes(tmp); skip = max(1, n // 100); cm = _cmap(p, render.FLOWZOO_WATER)
    vmax = 1.2 * np.sqrt(2 * float(p["gravity"]) * H); frames = []
    for i in range(0, n, skip):
        d = np.fromfile(Path(tmp) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3)
        fig = plt.figure(figsize=(6.4, 6.4 * Ly / Lx), dpi=110)
        ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(render.INK)
        fig.patch.set_facecolor(render.INK)
        ax.scatter(d[:, 0], d[:, 1], c=np.clip(d[:, 2] / vmax, 0, 1), cmap=cm, s=6,
                   edgecolors="none")
        ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
        fig.canvas.draw(); w, h = fig.canvas.get_width_height()
        frames.append(np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8)
                      .reshape(h, w, 4)[..., :3].copy())
        plt.close(fig)
    return frames, f"dam break  {len(d)} particles"


def _run_spectral(p, pr, tmp):
    from .spectral import Spectral2D, double_shear_layer
    s = _res(p); n = int(256 * s); steps = int(2800 * _durv(p)); nu = float(p["viscosity"])
    sim = Spectral2D(n=n, nu=nu)
    wh = double_shear_layer(n, amp=float(p["perturbation"])); dt = 0.4 * (2 * np.pi / n)
    view = p.get("view", "Vorticity"); cm = _cmap(p, render.FLOWZOO_CURL)
    pr(f"spectral {n}×{n}, ν={nu:.1e}, {steps} steps ({view})…")
    every = max(1, steps // (55 if view == "Streamlines" else 100))
    frames = []; vlim = None
    for st in range(steps + 1):
        if st % every == 0:
            if view == "Streamlines":
                u, v = sim.velocity(wh)
                frames.append(render.streamlines_rgb(u, v, cmap=_cmap(p, render.FLOWZOO_EMBER)))
            elif view == "Speed":
                u, v = sim.velocity(wh); sp = np.sqrt(u * u + v * v)
                if vlim is None:
                    vlim = np.percentile(sp, 99.5) + 1e-12
                frames.append(render.field_to_rgb(sp, _cmap(p, render.FLOWZOO_EMBER), 0, vlim, upscale=1))
            else:
                w = sim.vorticity(wh)
                if vlim is None:
                    vlim = np.percentile(np.abs(w), 99.0)
                frames.append(render.field_to_rgb(w, cm, -vlim, vlim, upscale=1))
        wh = sim.step(wh, dt)
    return frames, f"Kelvin–Helmholtz  {n}×{n}  ({view})"


EXHIBITS = {
    "Vortex street (LBM)": {
        "params": [_f("reynolds", "Reynolds number", 160, 60, 1000, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   _f("diameter", "Cylinder diameter (cells)", 34, 12, 70, "Geometry",
                      "Cylinder size. Larger obstacle → larger, slower-shedding wake."),
                   _P_VIEW, P_RES(), P_DUR(), P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_vortex(p, pr, t)},
    "Flow around your name (LBM)": {
        "params": [{"name": "text", "label": "Text", "type": "str", "default": "FlowZoo",
                    "group": "Geometry", "help": "The word(s) the flow sheds vortices off. "
                    "Short = crispest."},
                   _f("font", "Letter size (frac.)", 0.34, 0.15, 0.6, "Geometry",
                      "Letter height as a fraction of the domain height."),
                   _f("reynolds", "Reynolds number", 600, 150, 1500, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   _P_VIEW, P_RES(), P_DUR(), P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_lbm_text(p, pr, t)},
    "Smoke plume (Navier–Stokes)": {
        "params": [_f("buoyancy", "Buoyancy", 2.5e-3, 5e-4, 6e-3, "Physics", _H["buoy"]),
                   _f("confinement", "Vorticity confinement", 8, 0, 20, "Physics", _H["conf"]),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"]),
                   _f("source", "Source width (×)", 1.0, 0.3, 3.0, "Geometry",
                      "Width of the hot source at the floor. Wider → a fatter plume."),
                   P_RES(), P_DUR(), P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_ns("smoke", p, pr, t)},
    "Rayleigh–Taylor (Navier–Stokes)": {
        "params": [_f("gravity", "Gravity", 1.2e-3, 4e-4, 3e-3, "Physics", _H["grav"]),
                   _f("viscosity", "Viscosity", 1.5e-4, 3e-5, 5e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Interface ripple (×)", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the initial interface ripple that seeds the fingers."),
                   P_RES(), P_DUR(), P_CMAP("Hot / Cold")],
        "run": lambda p, pr, t: _run_ns("rt", p, pr, t)},
    "Explosion (Compressible)": {
        "params": [_f("pressure", "Blast pressure", 10.0, 2.0, 40.0, "Physics",
                      "Pressure inside the charge. Higher → a stronger, faster shock."),
                   _f("charge", "Charge size (frac.)", 0.06, 0.02, 0.18, "Geometry",
                      "Radius of the high-pressure charge as a fraction of the domain width."),
                   _f("debris", "Debris particles", 200, 0, 800, "Render",
                      "Glowing debris scattered across the domain and swept outward by the "
                      "blast (visual only)."),
                   _P_VIEW_C, P_RES(), P_DUR(), P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_euler("blast", p, pr, t)},
    "Shock–bubble (Compressible)": {
        "params": [_f("bubble", "Bubble size (frac.)", 0.18, 0.08, 0.32, "Geometry",
                      "Light-gas bubble radius as a fraction of the domain height."),
                   _P_VIEW_C, P_RES(), P_DUR(), P_CMAP("Ember (fire)")],
        "run": lambda p, pr, t: _run_euler("bubble", p, pr, t)},
    "Dam break (SPH)": {
        "params": [_f("width", "Dam width (m)", 1.0, 0.4, 2.0, "Geometry",
                      "Initial water-column width."),
                   _f("height", "Dam height (m)", 2.0, 0.6, 3.0, "Geometry",
                      "Initial water-column height."),
                   _f("particles", "Particles (≈)", 3000, 600, 12000, "Geometry",
                      "Approximate number of SPH particles. More → finer splash, slower."),
                   _f("gravity", "Gravity (m/s²)", 9.81, 1.0, 25.0, "Physics",
                      "Gravitational acceleration pulling the column down."),
                   P_DUR(), P_CMAP("Ocean (water)")],
        "run": lambda p, pr, t: _run_dam(p, pr, t)},
    "Kelvin–Helmholtz (Spectral)": {
        "params": [_f("viscosity", "Viscosity", 8e-5, 1e-5, 4e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Shear perturbation", 0.05, 0.005, 0.2, "Physics",
                      "Strength of the initial shear-layer kick that seeds the billows."),
                   _P_VIEW, P_RES(), P_DUR(), P_CMAP("Curl (cyan–amber)")],
        "run": lambda p, pr, t: _run_spectral(p, pr, t)},
}


# short description, governing equation (matplotlib mathtext), and demo clip
META = {
    "Vortex street (LBM)": {
        "method": "Lattice Boltzmann · D2Q9",
        "blurb": "Flow past a cylinder sheds a periodic train of alternating vortices — "
                 "the wake you see behind bridge piers and downwind of islands. Validated "
                 "against the Strouhal number (St ≈ 0.2).",
        "eq": r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$",
        "demo": "results/vortex_street.gif"},
    "Flow around your name (LBM)": {
        "method": "Lattice Boltzmann · D2Q9",
        "blurb": "The same solver, but the obstacle is text you type — watch vortices peel "
                 "off the letters. Lattice Boltzmann handles arbitrary geometry for free.",
        "eq": r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$",
        "demo": "results/flow_around_flowzoo.gif"},
    "Smoke plume (Navier–Stokes)": {
        "method": "Incompressible Navier–Stokes · projection",
        "blurb": "A hot, dyed source rises into a swirling buoyant plume — the incompressible "
                 "Navier–Stokes equations with Boussinesq buoyancy and vorticity confinement.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\cdot\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f},\quad \nabla\cdot\mathbf{u}=0$",
        "demo": "results/smoke_plume.gif"},
    "Rayleigh–Taylor (Navier–Stokes)": {
        "method": "Incompressible Navier–Stokes · projection",
        "blurb": "Heavy fluid resting on light fluid under gravity is unstable: the interface "
                 "rolls up into the classic mushroom-cap plumes.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\cdot\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}-g\,\rho\,\hat{\mathbf{y}}$",
        "demo": "results/rayleigh_taylor.gif"},
    "Explosion (Compressible)": {
        "method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A high-pressure charge bursts into ambient gas, launching an expanding "
                 "shock wave (shown in schlieren) that flings debris across the domain.",
        "eq": r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\quad \mathbf{U}=[\rho,\rho u,\rho v,E]$",
        "demo": "results/explosion.gif"},
    "Shock–bubble (Compressible)": {
        "method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A planar shock sweeps over a light-gas bubble; the density mismatch rolls "
                 "it into a vortex pair (a Richtmyer–Meshkov-type instability).",
        "eq": r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\quad \mathbf{U}=[\rho,\rho u,\rho v,E]$",
        "demo": "results/shock_bubble.gif"},
    "Dam break (SPH)": {
        "method": "Smoothed-Particle Hydrodynamics",
        "blurb": "A column of water collapses and surges across a tank — a meshfree, "
                 "particle-based free-surface flow. Validated against the dam-break front speed.",
        "eq": r"$\dfrac{D\mathbf{v}_i}{Dt}=-\sum_j m_j\!\left(\dfrac{p_i}{\rho_i^2}+\dfrac{p_j}{\rho_j^2}\right)\nabla W_{ij}+\mathbf{g}$",
        "demo": "results/dam_break.gif"},
    "Kelvin–Helmholtz (Spectral)": {
        "method": "Pseudo-spectral · FFT",
        "blurb": "A shear layer between two streams rolls up into Kelvin–Helmholtz billows "
                 "that cascade toward 2D turbulence — solved with FFTs to spectral accuracy.",
        "eq": r"$\partial_t\omega+(\mathbf{u}\cdot\nabla)\omega=\nu\nabla^2\omega,\quad \nabla^2\psi=-\omega$",
        "demo": "results/turbulence.gif"},
}


def run_exhibit(name, params, progress=lambda s: None):
    """Run an exhibit; return (frames:list[HxWx3 uint8], info:str)."""
    spec = EXHIBITS[name]
    full = {q["name"]: q["default"] for q in spec["params"]}
    full.update(params or {})
    with tempfile.TemporaryDirectory() as tmp:
        return spec["run"](full, progress, tmp)
