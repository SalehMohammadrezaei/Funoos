"""FlowZoo engine: solve an exhibit, then render any visualization on demand.

`solve_exhibit(name, params)` runs the solver once and returns a Result holding
the raw fields. `Result.render(view, colormap)` turns those into RGB frames —
so a GUI can switch Vorticity / Speed / Streamlines / Density … instantly
without re-running. `run_exhibit(...)` is a convenience that solves and renders
the default view (used by the command-line demos).

Each exhibit exposes a parameter spec (geometry + physics + render, with help
text and ranges); `view` and `colormap` are chosen *after* the run.
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
    return b[: nx * ny].reshape(ny, nx).copy(), b[nx * ny:].reshape(ny, nx).copy()


def _read_scalar(d, i, nx, ny):
    return np.fromfile(Path(d) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(ny, nx).copy()


def _nframes(d):
    return int([l.split()[1] for l in (Path(d) / "meta.txt").read_text().splitlines()
                if l.startswith("nframes")][0])


RES = {"Low (fast)": 0.6, "Medium": 1.0, "High": 1.35, "Ultra (slow)": 1.8}
VIEWS = {"lbm": ["Vorticity", "Speed", "Streamlines"],
         "spectral": ["Vorticity", "Speed", "Streamlines"],
         "density": ["Schlieren", "Density"],
         "scalar": ["Field"], "particles": ["Particles"]}
DEFCMAP = {"lbm": "Curl (cyan–amber)", "spectral": "Curl (cyan–amber)",
           "density": "Ember (fire)", "scalar": "Ember (fire)", "particles": "Ocean (water)"}


def _res(p):
    return RES.get(p.get("resolution", "Medium"), 1.0)


def _durv(p):
    return float(p.get("duration", 1.0))


# ---------- Result: holds raw fields, renders any view on demand ----------
class Result:
    def __init__(self, kind, raw, info, mask=None, hints=None):
        self.kind, self.raw, self.info = kind, raw, info
        self.mask, self.hints = mask, (hints or {})

    @property
    def views(self):
        return VIEWS[self.kind]

    def render(self, view=None, colormap=None):
        view = view or self.views[0]
        cm = render.COLORMAPS.get(colormap, render.COLORMAPS[DEFCMAP[self.kind]]) \
            if colormap else render.COLORMAPS[DEFCMAP[self.kind]]
        if self.kind in ("lbm", "spectral"):
            return self._render_vel(view, cm)
        if self.kind == "density":
            return self._render_density(view, cm)
        if self.kind == "scalar":
            v0, v1 = self.hints["vlim"]
            return [render.add_colorbar(
                render.field_to_rgb(s, cm, v0, v1, upscale=1, gamma=self.hints["gamma"]),
                cm, v0, v1, self.hints.get("label", "")) for s in self.raw]
        if self.kind == "particles":
            return self._render_particles(cm)

    def _render_vel(self, view, cm):
        if view == "Streamlines":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in self.raw]
            vmax = np.percentile(sp[-1], 99.5) + 1e-12
            return [render.add_colorbar(
                render.streamlines_rgb(ux, uy, cmap=cm, mask=self.mask, vmax=vmax),
                cm, 0, vmax, "|u|") for ux, uy in self.raw]
        if view == "Speed":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in self.raw]
            vmax = np.percentile(sp[-1], 99.5) + 1e-12
            return [render.add_colorbar(
                render.field_to_rgb(s, cm, 0, vmax, mask=self.mask, mask_color=render.SOLID,
                                    upscale=1), cm, 0, vmax, "|u|") for s in sp]
        vt = [render.vorticity(ux, uy) for ux, uy in self.raw]
        vmax = np.percentile(np.abs(vt[-1]), 99.0)
        return [render.add_colorbar(
            render.field_to_rgb(w, cm, -vmax, vmax, mask=self.mask, mask_color=render.SOLID,
                                upscale=1), cm, -vmax, vmax, "vorticity ω") for w in vt]

    def _render_density(self, view, cm):
        out = []
        h = self.hints; deb = h.get("debris", 0); nx, ny = h.get("nx"), h.get("ny")
        if view == "Density":
            dv0, dv1 = np.percentile(self.raw[-1], 1), np.percentile(self.raw[-1], 99.5) + 1e-6
        else:
            sv = np.percentile(render.schlieren(self.raw[-1]), 99.5) + 1e-6
        if deb and h.get("mode") == "blast" and view == "Schlieren":
            rng = np.random.default_rng(7)
            bx = rng.uniform(0, nx, deb); by = rng.uniform(0, ny, deb)
            cx, cy = nx / 2, ny / 2
            dist = np.hypot(bx - cx, by - cy) + 1e-6; ang = np.arctan2(by - cy, bx - cx)
            push = rng.uniform(0.5, 1.0, deb); Rmax = 0.75 * np.hypot(nx, ny) / 2
        for fi, rho in enumerate(self.raw):
            if view == "Density":
                out.append(render.add_colorbar(
                    render.field_to_rgb(rho, cm, dv0, dv1, upscale=1), cm, dv0, dv1, "ρ"))
                continue
            sch = render.schlieren(rho)
            img = render.field_to_rgb(sch, cm, 0.0, sv, upscale=1, gamma=0.7)
            if deb and h.get("mode") == "blast":
                tau = fi / max(1, len(self.raw) - 1); Rs = Rmax * tau * 1.25
                passed = Rs > dist; disp = np.where(passed, (Rs - dist) * push * 0.9, 0.0)
                px = bx + np.cos(ang) * disp; py = by + np.sin(ang) * disp; iy = ny - 1 - py
                keep = (px > 1) & (px < nx - 1) & (iy > 1) & (iy < ny - 1)
                img = render.overlay_particles(img, px[keep], iy[keep],
                                               np.where(passed[keep], 1.9, 1.0))
            out.append(render.add_colorbar(img, cm, 0, sv, "|∇ρ|"))
        return out

    def _render_particles(self, cm):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        Lx, Ly, vmax = self.hints["Lx"], self.hints["Ly"], self.hints["vmax"]
        out = []
        for d in self.raw:
            fig = plt.figure(figsize=(6.4, 6.4 * Ly / Lx), dpi=110)
            ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(render.INK)
            fig.patch.set_facecolor(render.INK)
            ax.scatter(d[:, 0], d[:, 1], c=np.clip(d[:, 2] / vmax, 0, 1), cmap=cm, s=6,
                       edgecolors="none")
            ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
            fig.canvas.draw(); w, hh = fig.canvas.get_width_height()
            rgb = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(hh, w, 4)[..., :3].copy()
            plt.close(fig)
            out.append(render.add_colorbar(rgb, cm, 0, vmax, "|v|"))
        return out


# ---------- parameter descriptors (pre-run only) ----------
def P_RES(help="Grid resolution. Higher = sharper detail but slower."):
    return {"name": "resolution", "label": "Resolution", "type": "choice",
            "choices": list(RES), "default": "Medium", "group": "Render", "help": help}


def P_DUR(help="Simulation length multiplier — set any value (1.0 = default)."):
    return {"name": "duration", "label": "Duration (×)", "type": "float", "default": 1.0,
            "min": 0.2, "max": 6.0, "group": "Render", "help": help}


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


# ---------- runners (SOLVE → raw fields) ----------
def _solve_vortex(p, pr, tmp):
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
    n = _nframes(tmp); use = range(n // 5, n, max(1, (n - n // 5) // 90))
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    return Result("lbm", raw, f"vortex street  Re={Re:.0f}  {nx}×{ny}", mask=mask)


def _solve_text(p, pr, tmp):
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
    n = _nframes(tmp); use = range(n // 5, n, max(1, (n - n // 5) // 90))
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    return Result("lbm", raw, f"flow around '{p['text']}'  {nx}×{ny}", mask=mask)


def _solve_ns(mode, p, pr, tmp):
    s = _res(p); nx, ny = int(280 * s), int(440 * s); steps = int(4800 * _durv(p))
    _ensure(_bin("incompressible", "ins2d"))
    args = [str(_bin("incompressible", "ins2d")), "--mode", mode, "--nx", str(nx),
            "--ny", str(ny), "--steps", str(steps), "--save_every", str(max(1, steps // 110)),
            "--out", tmp, "--visc", str(p["viscosity"])]
    if mode == "smoke":
        args += ["--buoy", str(p["buoyancy"]), "--conf", str(p["confinement"]), "--srcw", str(p["source"])]
        hints = {"vlim": (0.0, 0.85), "gamma": 0.85, "label": "smoke density"}
    else:
        args += ["--grav", str(p["gravity"]), "--pert", str(p["perturbation"]), "--conf", "0", "--iters", "80"]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "density ρ"}
    pr(f"Navier–Stokes ({mode}) {nx}×{ny}, {steps} steps…")
    subprocess.run(args, check=True)
    n = _nframes(tmp); skip = max(1, n // 100)
    raw = [_read_scalar(tmp, i, nx, ny) for i in range(0, n, skip)]
    r = Result("scalar", raw, f"{mode}  {nx}×{ny}", hints=hints)
    return r


def _solve_euler(mode, p, pr, tmp):
    s = _res(p)
    if mode == "blast":
        nx = ny = int(420 * s); tend = 70 * _durv(p)
        extra = ["--p0", str(p["pressure"]), "--radius", str(p["charge"])]
        hints = {"mode": "blast", "debris": int(p.get("debris", 0)), "nx": nx, "ny": ny}
    else:
        nx, ny = int(620 * s), int(320 * s); tend = 230 * _durv(p)
        extra = ["--bubr", str(p["bubble"])]; hints = {"mode": "bubble", "nx": nx, "ny": ny}
    _ensure(_bin("compressible", "euler2d"))
    pr(f"compressible Euler ({mode}) {nx}×{ny}…")
    subprocess.run([str(_bin("compressible", "euler2d")), "--mode", mode, "--nx", str(nx),
                    "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4", "--steps", "200000",
                    "--save_every", "12", "--out", tmp] + extra, check=True)
    n = _nframes(tmp); skip = max(1, n // 100)
    raw = [_read_scalar(tmp, i, nx, ny) for i in range(0, n, skip)]
    return Result("density", raw, f"{mode}  {nx}×{ny}", hints=hints)


def _solve_dam(p, pr, tmp):
    a, H, Lx, Ly = float(p["width"]), float(p["height"]), 5.0, 3.2
    npart = max(400.0, float(p["particles"]))
    dp = float(np.clip(np.sqrt(a * H / npart), 0.014, 0.08))
    _ensure(_bin("sph", "sph2d"))
    pr(f"SPH dam break (~{int(a * H / dp / dp)} particles)…")
    subprocess.run([str(_bin("sph", "sph2d")), "--a", str(a), "--H", str(H), "--Lx", str(Lx),
                    "--Ly", str(Ly), "--dp", str(dp), "--g", str(p["gravity"]),
                    "--tend", str(1.6 * _durv(p)), "--save_every", "60", "--out", tmp], check=True)
    n = _nframes(tmp); skip = max(1, n // 100)
    raw = [np.fromfile(Path(tmp) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3)
           for i in range(0, n, skip)]
    return Result("particles", raw, f"dam break  {len(raw[0])} particles",
                  hints={"Lx": Lx, "Ly": Ly, "vmax": 1.2 * np.sqrt(2 * float(p["gravity"]) * H)})


def _solve_spectral(p, pr, tmp):
    from .spectral import Spectral2D, double_shear_layer
    s = _res(p); n = int(256 * s); steps = int(2800 * _durv(p)); nu = float(p["viscosity"])
    sim = Spectral2D(n=n, nu=nu)
    wh = double_shear_layer(n, amp=float(p["perturbation"])); dt = 0.4 * (2 * np.pi / n)
    pr(f"spectral {n}×{n}, ν={nu:.1e}, {steps} steps…")
    raw = []
    for st in range(steps + 1):
        if st % max(1, steps // 90) == 0:
            u, v = sim.velocity(wh)
            raw.append((sim.vorticity(wh), u, v))
        wh = sim.step(wh, dt)
    # store as (ux,uy) pairs + carry vorticity by reusing 'lbm' renderer on (u,v);
    # vorticity recomputed from (u,v) matches sim vorticity to round-off.
    vel = [(u, v) for (_w, u, v) in raw]
    return Result("spectral", vel, f"Kelvin–Helmholtz  {n}×{n}")


EXHIBITS = {
    "Vortex street (LBM)": {
        "params": [_f("reynolds", "Reynolds number", 160, 60, 1000, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   _f("diameter", "Cylinder diameter (cells)", 34, 12, 70, "Geometry",
                      "Cylinder size. Larger obstacle → larger, slower-shedding wake."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_vortex(p, pr, t)},
    "Flow around your name (LBM)": {
        "params": [{"name": "text", "label": "Text", "type": "str", "default": "FlowZoo",
                    "group": "Geometry", "help": "The word(s) the flow sheds vortices off."},
                   _f("font", "Letter size (frac.)", 0.34, 0.15, 0.6, "Geometry",
                      "Letter height as a fraction of the domain height."),
                   _f("reynolds", "Reynolds number", 600, 150, 1500, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_text(p, pr, t)},
    "Smoke plume (Navier–Stokes)": {
        "params": [_f("buoyancy", "Buoyancy", 2.5e-3, 5e-4, 6e-3, "Physics", _H["buoy"]),
                   _f("confinement", "Vorticity confinement", 8, 0, 20, "Physics", _H["conf"]),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"]),
                   _f("source", "Source width (×)", 1.0, 0.3, 3.0, "Geometry",
                      "Width of the hot source at the floor."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("smoke", p, pr, t)},
    "Rayleigh–Taylor (Navier–Stokes)": {
        "params": [_f("gravity", "Gravity", 1.2e-3, 4e-4, 3e-3, "Physics", _H["grav"]),
                   _f("viscosity", "Viscosity", 1.5e-4, 3e-5, 5e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Interface ripple (×)", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the initial interface ripple that seeds the fingers."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rt", p, pr, t)},
    "Explosion (Compressible)": {
        "params": [_f("pressure", "Blast pressure", 10.0, 2.0, 40.0, "Physics",
                      "Pressure inside the charge. Higher → a stronger, faster shock."),
                   _f("charge", "Charge size (frac.)", 0.06, 0.02, 0.18, "Geometry",
                      "Radius of the high-pressure charge as a fraction of the domain width."),
                   _f("debris", "Debris particles", 200, 0, 800, "Render",
                      "Glowing debris scattered across the domain and swept outward by the "
                      "blast (visual only)."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("blast", p, pr, t)},
    "Shock–bubble (Compressible)": {
        "params": [_f("bubble", "Bubble size (frac.)", 0.18, 0.08, 0.32, "Geometry",
                      "Light-gas bubble radius as a fraction of the domain height."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("bubble", p, pr, t)},
    "Dam break (SPH)": {
        "params": [_f("width", "Dam width (m)", 1.0, 0.4, 2.0, "Geometry", "Initial column width."),
                   _f("height", "Dam height (m)", 2.0, 0.6, 3.0, "Geometry", "Initial column height."),
                   _f("particles", "Particles (≈)", 3000, 600, 12000, "Geometry",
                      "Approximate number of SPH particles. More → finer splash, slower."),
                   _f("gravity", "Gravity (m/s²)", 9.81, 1.0, 25.0, "Physics",
                      "Gravitational acceleration pulling the column down."),
                   P_DUR()],
        "solve": lambda p, pr, t: _solve_dam(p, pr, t)},
    "Kelvin–Helmholtz (Spectral)": {
        "params": [_f("viscosity", "Viscosity", 8e-5, 1e-5, 4e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Shear perturbation", 0.05, 0.005, 0.2, "Physics",
                      "Strength of the initial shear-layer kick that seeds the billows."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_spectral(p, pr, t)},
}

META = {
    "Vortex street (LBM)": {"method": "Lattice Boltzmann · D2Q9",
        "blurb": "Flow past a cylinder sheds a periodic train of alternating vortices — the "
                 "wake behind bridge piers and downwind of islands.",
        "eq": r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$",
        "numerics": "D2Q9 lattice, BGK collision, half-way bounce-back on the obstacle, "
                    "periodic transverse boundaries; viscosity ν=(τ−½)/3.",
        "validation": "Strouhal number St ≈ 0.20 at Re ≈ 160 (matches the textbook value).",
        "demo": "results/vortex_street.gif"},
    "Flow around your name (LBM)": {"method": "Lattice Boltzmann · D2Q9",
        "blurb": "The same kinetic solver, but the obstacle is text you type — vortices peel "
                 "off the letters. LBM handles arbitrary geometry for free.",
        "eq": r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$",
        "numerics": "Text is rasterized to a solid mask; bounce-back applies on every glyph cell.",
        "validation": "Inherits the validated D2Q9 solver (St ≈ 0.2 on a cylinder).",
        "demo": "results/flow_around_flowzoo.gif"},
    "Smoke plume (Navier–Stokes)": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "A hot, dyed source rises into a swirling buoyant plume.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\cdot\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f},\ \ \nabla\cdot\mathbf{u}=0$",
        "numerics": "Semi-Lagrangian advection, red-black SOR pressure projection, Boussinesq "
                    "buoyancy, vorticity confinement.",
        "validation": "Divergence-free to the projection tolerance; stable buoyant transport.",
        "demo": "results/smoke_plume.gif"},
    "Rayleigh–Taylor (Navier–Stokes)": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "Heavy fluid over light under gravity rolls into mushroom-cap plumes.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\cdot\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}-g\,\rho\,\hat{\mathbf{y}}$",
        "numerics": "Same projection solver; a density scalar drives the buoyancy term.",
        "validation": "Characteristic mushroom roll-up; growth set by gravity & viscosity.",
        "demo": "results/rayleigh_taylor.gif"},
    "Explosion (Compressible)": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A high-pressure charge bursts into ambient gas, launching an expanding shock.",
        "eq": r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\ \ \mathbf{U}=[\rho,\rho u,\rho v,E]$",
        "numerics": "MUSCL reconstruction + minmod limiter, HLLC Riemann solver, SSP-RK2, γ=1.4.",
        "validation": "Same solver matches the exact Sod shock tube to ~0.002 mean error.",
        "demo": "results/explosion.gif"},
    "Shock–bubble (Compressible)": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A planar shock rolls a light-gas bubble into a vortex pair (Richtmyer–Meshkov).",
        "eq": r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\ \ \mathbf{U}=[\rho,\rho u,\rho v,E]$",
        "numerics": "MUSCL+HLLC; a low-density circular bubble in a post-shock inflow.",
        "validation": "Same HLLC solver validated on the exact Sod solution.",
        "demo": "results/shock_bubble.gif"},
    "Dam break (SPH)": {"method": "Smoothed-Particle Hydrodynamics",
        "blurb": "A water column collapses and surges across a tank — meshfree, particle-based.",
        "eq": r"$\dfrac{D\mathbf{v}_i}{Dt}=-\sum_j m_j\!\left(\dfrac{p_i}{\rho_i^2}+\dfrac{p_j}{\rho_j^2}\right)\nabla W_{ij}+\mathbf{g}$",
        "numerics": "Weakly-compressible SPH, cubic-spline kernel, Tait EOS (p≥0), Monaghan "
                    "artificial viscosity, grid neighbor search.",
        "validation": "Surge-front speed in the physical range of the Ritter dry-bed limit.",
        "demo": "results/dam_break.gif"},
    "Kelvin–Helmholtz (Spectral)": {"method": "Pseudo-spectral · FFT",
        "blurb": "A shear layer rolls up into billows cascading toward 2D turbulence.",
        "eq": r"$\partial_t\omega+(\mathbf{u}\cdot\nabla)\omega=\nu\nabla^2\omega,\ \ \nabla^2\psi=-\omega$",
        "numerics": "Vorticity–streamfunction form, 2/3-rule dealiasing, RK4 time stepping.",
        "validation": "Inviscid energy conserved to ≈ 1.5×10⁻⁷ — the spectral-accuracy signature.",
        "demo": "results/turbulence.gif"},
}


def solve_exhibit(name, params, progress=lambda s: None):
    """Run the solver once; return a Result you can .render(view, colormap) from."""
    spec = EXHIBITS[name]
    full = {q["name"]: q["default"] for q in spec["params"]}
    full.update(params or {})
    with tempfile.TemporaryDirectory() as tmp:
        return spec["solve"](full, progress, tmp)


def run_exhibit(name, params, progress=lambda s: None, view=None, colormap=None):
    """Convenience: solve and render the default (or given) view. Used by demos."""
    r = solve_exhibit(name, params, progress)
    return r.render(view, colormap), r.info
