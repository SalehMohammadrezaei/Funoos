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

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

from . import render, geometry

_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
SOLVERS = _BASE / "solvers"
EXE = ".exe" if sys.platform.startswith("win") else ""
# 2D grids are modest — ~8 threads is the throughput sweet spot (more = overhead).
_ENV = {**os.environ, "OMP_NUM_THREADS": str(min(8, os.cpu_count() or 4))}


def _bin(d, name):
    return SOLVERS / d / (name + EXE)


def _ensure(b):
    b = Path(b)
    frozen = sys.platform.startswith("win") or getattr(sys, "frozen", False)
    if frozen:
        if not b.exists():
            raise FileNotFoundError(f"solver not found: {b}. Build it first "
                                    f"(see docs/windows_build.md).")
        return
    # dev (source) build: (re)compile if the binary is missing OR the source is newer,
    # so running the app always picks up edited solver code — no stale binaries.
    src = b.with_suffix(".cpp")
    stale = b.exists() and src.exists() and src.stat().st_mtime > b.stat().st_mtime
    if not b.exists() or stale:
        subprocess.run(["make", "-C", str(b.parent)], check=True, env=_ENV)


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
         "density": ["Schlieren", "Density", "Speed"],
         "ns": ["Dye", "Speed", "Vorticity", "Streamlines"],
         "particles": ["Particles", "Foam & spray", "Speed field"]}
DEFCMAP = {"lbm": "Curl (cyan–amber)", "spectral": "Curl (cyan–amber)",
           "density": "Ember (fire)", "ns": "Ember (fire)", "particles": "Ocean (water)"}


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
            return self._render_vel(self.raw, view, cm, self.mask)
        if self.kind == "density":
            return self._render_density(view, cm)
        if self.kind == "ns":
            if view == "Dye":
                v0, v1 = self.hints["vlim"]
                return [render.add_colorbar(
                    render.field_to_rgb(s, cm, v0, v1, upscale=1, gamma=self.hints["gamma"]),
                    cm, v0, v1, self.hints.get("label", "")) for s in self.raw]
            return self._render_vel(self.hints["vel"], view, cm, None)
        if self.kind == "particles":
            if view == "Speed field":
                return self._render_sph_field(cm)
            return self._render_particles(cm, foam=(view == "Foam & spray"))

    def _render_vel(self, vel, view, cm, mask):
        if view == "Streamlines":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in vel]
            vmax = np.percentile(sp[-1], 99.5) + 1e-12
            return [render.add_colorbar(
                render.streamlines_rgb(ux, uy, cmap=cm, mask=mask, vmax=vmax),
                cm, 0, vmax, "|u|") for ux, uy in vel]
        if view == "Speed":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in vel]
            vmax = np.percentile(sp[-1], 99.5) + 1e-12
            return [render.add_colorbar(
                render.field_to_rgb(s, cm, 0, vmax, mask=mask, mask_color=render.SOLID,
                                    upscale=1), cm, 0, vmax, "|u|") for s in sp]
        vt = [render.vorticity(ux, uy) for ux, uy in vel]
        vmax = np.percentile(np.abs(vt[-1]), 99.0) + 1e-12
        return [render.add_colorbar(
            render.field_to_rgb(w, cm, -vmax, vmax, mask=mask, mask_color=render.SOLID,
                                upscale=1), cm, -vmax, vmax, "vorticity ω") for w in vt]

    def _render_density(self, view, cm):
        out = []
        h = self.hints; deb = h.get("debris", 0); nx, ny = h.get("nx"), h.get("ny")
        solid = h.get("solid"); city = solid is not None
        failt = h.get("failt")                              # per-block failure fraction, -1=intact
        CONCRETE = np.array([78, 82, 102], np.uint8)

        def standing(tau):
            # blocks still in place at time-fraction tau (failed ones have flown off)
            if failt is None:
                return solid[::-1]
            vis = solid & ((failt < 0) | (tau < failt))
            return vis[::-1]

        if view == "Speed":
            vel = h.get("vel")
            sp = [np.hypot(ux, uy) for ux, uy in vel]
            ref = sp[-1] if not city else sp[-1][~solid]
            vmax = np.percentile(ref, 99.0) + 1e-9
            res = []
            n = len(sp)
            for fi, s in enumerate(sp):
                img = render.field_to_rgb(s, cm, 0, vmax, upscale=1)
                if city:
                    img = np.array(img); img[standing(fi / max(1, n - 1))] = CONCRETE
                res.append(render.add_colorbar(img, cm, 0, vmax, "|u|"))
            return res
        if view == "Density":
            dv0, dv1 = np.percentile(self.raw[-1], 1), np.percentile(self.raw[-1], 99.5) + 1e-6
        else:
            # ignore the stiff solid cells (ρ=6, huge edge gradients) when scaling
            sref = render.schlieren(self.raw[-1])
            if city: sref = sref[~solid]
            sv = np.percentile(sref, 99.5) + 1e-6
        if deb and h.get("mode") == "blast" and view == "Schlieren":
            rng = np.random.default_rng(7)
            if city:
                # debris IS the masonry: seed on blocks that actually fail, and launch
                # each fragment exactly when its block fails (failt), not on a guess
                fy_, fx_ = np.where(solid & (failt >= 0)) if failt is not None else np.where(solid)
                if len(fx_):
                    pick = rng.integers(0, len(fx_), deb)
                    bx = fx_[pick] + rng.uniform(-1, 1, deb); by = fy_[pick] + rng.uniform(-1, 1, deb)
                    flaunch = (failt[fy_[pick], fx_[pick]] if failt is not None
                               else np.zeros(deb))
                else:                                      # nothing failed → no debris
                    bx = by = flaunch = np.zeros(0); deb = 0
                cx, cy = nx * 0.20, ny * 0.14              # the ground-burst origin
            else:
                bx = rng.uniform(0, nx, deb); by = rng.uniform(0, ny, deb)
                cx, cy = nx / 2, ny / 2
                flaunch = None
            dist = np.hypot(bx - cx, by - cy) + 1e-6; ang = np.arctan2(by - cy, bx - cx)
            if city: ang += rng.uniform(-0.4, 0.4, deb)    # scatter the fragments
            push = rng.uniform(0.5, 1.0, deb); Rmax = 0.75 * np.hypot(nx, ny) / 2
        for fi, rho in enumerate(self.raw):
            tau = fi / max(1, len(self.raw) - 1)
            if view == "Density":
                img = np.array(render.field_to_rgb(rho, cm, dv0, dv1, upscale=1))
                if city: img[standing(tau)] = CONCRETE
                out.append(render.add_colorbar(img, cm, dv0, dv1, "ρ"))
                continue
            sch = render.schlieren(rho)
            img = render.field_to_rgb(sch, cm, 0.0, sv, upscale=1, gamma=0.7)
            if city:                                       # draw the towers that are still standing
                img = np.array(img); img[standing(tau)] = CONCRETE
            if deb and h.get("mode") == "blast":
                if city:                                   # fragment flies once its block fails
                    since = tau - flaunch
                else:
                    since = tau - dist / (Rmax * 1.25)     # open air: shock-front arrival
                disp = np.where(since > 0, since * Rmax * 1.25 * push * 0.7, 0.0)
                px = bx + np.cos(ang) * disp; py = by + np.sin(ang) * disp
                if city:                                   # ballistic arc: fling up, fall under gravity
                    py = py + np.where(since > 0, since * Rmax * 0.9 - (since ** 2) * Rmax * 2.2, 0.0)
                iy = ny - 1 - py
                heat = np.clip(np.where(since > 0, np.exp(-2.2 * since), 0.12), 0.08, 1.0)
                size = 1.0 + 1.8 * heat
                keep = (since > 0) & (px > 1) & (px < nx - 1) & (iy > 1) & (iy < ny - 1)
                img = render.overlay_particles(img, px[keep], iy[keep], size[keep], heat[keep])
            out.append(render.add_colorbar(img, cm, 0, sv, "|∇ρ|"))
        return out

    def _render_particles(self, cm, foam=False):
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        Lx, Ly, vmax = self.hints["Lx"], self.hints["Ly"], self.hints["vmax"]
        hull = self.hints.get("hull")
        # size markers to the particle spacing so the water reads as a continuous
        # body, not sparse dots (the dp→px→points² conversion for this figure)
        dp = self.hints.get("dp", 0.04); DPI = 110
        px_per_unit = 6.4 * DPI / Lx
        diam_pt = dp * px_per_unit / (DPI / 72.0)
        PSIZE = float(np.clip((diam_pt * 1.35) ** 2, 5.0, 44.0))
        out = []
        for fi, d in enumerate(self.raw):
            fig = plt.figure(figsize=(6.4, 6.4 * Ly / Lx), dpi=DPI)
            ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(render.INK)
            fig.patch.set_facecolor(render.INK)
            sp = np.clip(d[:, 2] / vmax, 0, 1)
            if foam:
                # deep water + whitewater on the fast (breaking/spray) particles
                ax.scatter(d[:, 0], d[:, 1], c="#173a6b", s=PSIZE, edgecolors="none")
                fast = sp > 0.45
                if fast.any():
                    ax.scatter(d[fast, 0], d[fast, 1], c="white", s=PSIZE * 0.7,
                               alpha=np.clip(sp[fast], 0.3, 0.95), edgecolors="none")
            else:
                # keep RESTING water clearly visible: floor the shade so v=0 is a
                # legible blue, not the near-black bottom of the colormap (otherwise
                # still water vanishes and only moving water shows — looks like it
                # "appears from nothing"). Brightness still rises with speed.
                shade = 0.34 + 0.66 * sp
                ax.scatter(d[:, 0], d[:, 1], c=shade, cmap=cm, vmin=0.0, vmax=1.0,
                           s=PSIZE, edgecolors="none")
            if hull is not None:
                hp = hull[fi]; ax.scatter(hp[:, 0], hp[:, 1], c="#c79a5b", s=PSIZE, edgecolors="none")
            ax.set_xlim(0, Lx); ax.set_ylim(0, Ly); ax.axis("off")
            fig.canvas.draw(); w, hh = fig.canvas.get_width_height()
            rgb = np.frombuffer(fig.canvas.buffer_rgba(), dtype=np.uint8).reshape(hh, w, 4)[..., :3].copy()
            plt.close(fig)
            out.append(rgb if foam else render.add_colorbar(rgb, cm, 0, vmax, "|v|"))
        return out

    def _render_sph_field(self, cm):
        # bin the particles onto a grid and reconstruct a smooth speed field (the
        # SPH "continuum" view) — the mesh-free analogue of the LBM Speed view
        Lx, Ly, vmax = self.hints["Lx"], self.hints["Ly"], self.hints["vmax"]
        gx = 150; gy = max(40, int(gx * Ly / Lx))

        def blur(a, k=2):
            w = np.ones(2 * k + 1) / (2 * k + 1)
            for ax in (0, 1):
                a = np.apply_along_axis(lambda m: np.convolve(m, w, mode="same"), ax, a)
            return a
        out = []
        for d in self.raw:
            ix = np.clip((d[:, 0] / Lx * gx).astype(int), 0, gx - 1)
            iy = np.clip((d[:, 1] / Ly * gy).astype(int), 0, gy - 1)
            cnt = np.zeros((gy, gx)); ssum = np.zeros((gy, gx))
            np.add.at(cnt, (iy, ix), 1.0)
            np.add.at(ssum, (iy, ix), d[:, 2])
            field = blur(ssum, 2) / (blur(cnt, 2) + 1e-6)
            field[blur(cnt, 2) < 0.05] = 0.0          # empty (air) cells stay dark
            out.append(render.add_colorbar(
                render.field_to_rgb(field, cm, 0, vmax, upscale=3), cm, 0, vmax, "|v|"))
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


def _when(qd, ctrl, vals):
    # mark a descriptor so the app only shows it when control `ctrl` ∈ vals
    qd = dict(qd); qd["when"] = (ctrl, vals); return qd


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
def _solve_windtunnel(p, pr, tmp):
    s = _res(p); nx, ny = int(900 * s), int(300 * s)
    Re = float(p["reynolds"]); U = float(p["speed"]); obs = p["obstacle"]
    cx, cy = nx // 4, ny // 2 + 2
    D = max(8.0, ny * float(p["size"]))                     # characteristic length
    if obs == "Your text":
        mask = geometry.text(nx, ny, p["text"], font_frac=0.34, x_frac=0.28, max_w_frac=0.5)
        D = ny * 0.34; probe = int(nx * 0.6)
    elif obs == "Square":
        mask = geometry.square(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    elif obs == "Diamond":
        mask = geometry.diamond(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    elif obs == "Airfoil":
        mask = geometry.airfoil(nx, ny, cx, cy, chord=D * 2.6, aoa_deg=float(p["angle"]))
        probe = cx + int(3 * D)
    else:                                                   # Cylinder
        mask = geometry.cylinder(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    tau = 0.5 + 3 * (U * D / Re)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    _ensure(_bin("lbm", "lbm2d"))
    steps = int(44000 * _durv(p))
    pr(f"LBM wind tunnel · {obs} · {nx}×{ny}, Re={Re:.0f}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(min(probe, nx - 2)), "--probe_y", str(ny // 2)],
                   check=True, env=_ENV)
    n = _nframes(tmp); use = range(n // 5, n, max(1, (n - n // 5) // 90))
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    return Result("lbm", raw, f"wind tunnel · {obs} · Re={Re:.0f} · {nx}×{ny}", mask=mask)


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
        args += ["--grav", str(p["gravity"]), "--pert", str(p["perturbation"]), "--conf", "0",
                 "--iters", "80", "--atwood", str(p.get("atwood", 1.0))]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "density ρ"}
    pr(f"Navier–Stokes ({mode}) {nx}×{ny}, {steps} steps…")
    subprocess.run(args, check=True, env=_ENV)
    n = _nframes(tmp); skip = max(1, n // 100); idx = list(range(0, n, skip))
    raw = [_read_scalar(tmp, i, nx, ny) for i in idx]

    def _rv(i):                                              # read the vel_*.bin field
        b = np.fromfile(Path(tmp) / f"vel_{i:05d}.bin", dtype=np.float32)
        return b[: nx * ny].reshape(ny, nx).copy(), b[nx * ny:].reshape(ny, nx).copy()
    hints["vel"] = [_rv(i) for i in idx]                     # for Speed/Vorticity/Streamlines
    return Result("ns", raw, f"{mode}  {nx}×{ny}", hints=hints)


def _solve_euler(mode, p, pr, tmp):
    s = _res(p)
    if mode == "blast":
        nx = ny = int(420 * s); tend = 70 * _durv(p)
        bld = 1 if p.get("scene") == "Shock hits a city" else 0
        extra = ["--p0", str(p["pressure"]), "--radius", str(p["charge"]), "--building", str(bld)]
        if bld:
            extra += ["--strength", str(p.get("strength", 1.0))]
        hints = {"mode": "blast", "debris": int(p.get("debris", 0)), "nx": nx, "ny": ny,
                 "building": bld}
    else:
        nx, ny = int(620 * s), int(320 * s); tend = 230 * _durv(p)
        nb = 2 if p.get("target") == "Two bubbles" else 1
        rho_b = float(p.get("densratio", 0.18)); mach = float(p.get("mach", 1.5))
        extra = ["--bubr", str(p["bubble"]), "--bubrho", str(rho_b), "--nbub", str(nb),
                 "--mach", str(mach)]
        hints = {"mode": "bubble", "nx": nx, "ny": ny}
    _ensure(_bin("compressible", "euler2d"))
    pr(f"compressible Euler ({mode}) {nx}×{ny}…")
    subprocess.run([str(_bin("compressible", "euler2d")), "--mode", mode, "--nx", str(nx),
                    "--ny", str(ny), "--tend", str(tend), "--cfl", "0.4", "--steps", "200000",
                    "--save_every", "12", "--out", tmp] + extra, check=True, env=_ENV)
    n = _nframes(tmp); skip = max(1, n // 100); idx = list(range(0, n, skip))
    raw = [_read_scalar(tmp, i, nx, ny) for i in idx]

    def _rv(i):
        b = np.fromfile(Path(tmp) / f"vel_{i:05d}.bin", dtype=np.float32)
        return b[: nx * ny].reshape(ny, nx).copy(), b[nx * ny:].reshape(ny, nx).copy()
    if (Path(tmp) / f"vel_{idx[0]:05d}.bin").exists():
        hints["vel"] = [_rv(i) for i in idx]
    sp = Path(tmp) / "solid.bin"
    if sp.exists():
        hints["solid"] = np.fromfile(sp, dtype=np.float32).reshape(ny, nx) > 0.5
    fp = Path(tmp) / "failt.bin"
    if fp.exists():
        hints["failt"] = np.fromfile(fp, dtype=np.float32).reshape(ny, nx)   # [0,1], -1=intact
    return Result("density", raw, f"{mode}  {nx}×{ny}", hints=hints)


_SPLASH_SCENE = {"Dam break": "dam", "Drop & splash": "drop", "Sloshing tank": "slosh",
                 "Pour into a glass": "pour", "Wavy ocean": "waves", "Ship on waves": "ship"}
_SPLASH_TANK = {"dam": (5.0, 3.2), "drop": (5.0, 3.2), "slosh": (5.0, 3.2),
                "pour": (2.2, 3.4), "waves": (6.0, 2.4), "ship": (6.0, 2.4)}


def _solve_dam(p, pr, tmp):
    sc = _SPLASH_SCENE.get(p.get("scene", "Dam break"), "dam")
    Lx, Ly = _SPLASH_TANK[sc]
    a = float(p.get("dropsize", 1.0)) if sc == "drop" else float(p["width"])
    H = float(p["height"])
    npart = max(500.0, float(p["particles"]))
    dp = float(np.clip(np.sqrt(Lx * Ly * 0.4 / npart), 0.02, 0.08))
    g = float(p["gravity"])
    args = [str(_bin("sph", "sph2d")), "--scene", sc, "--a", str(a), "--H", str(H),
            "--Lx", str(Lx), "--Ly", str(Ly), "--dp", str(dp), "--g", str(g),
            "--tend", str(2.0 * _durv(p)), "--save_every", "60", "--out", tmp]
    if sc == "drop":
        args += ["--dh", str(p.get("dropheight", 0.70))]
    elif sc == "slosh":
        args += ["--sloshA", str(p.get("sloshA", 0.7)), "--sloshT", str(p.get("sloshT", 1.1))]
    elif sc == "pour":
        args += ["--sw", str(p.get("spout", 0.045)), "--pourv", str(p.get("pourv", 2.2))]
    elif sc in ("waves", "ship"):
        args += ["--waveA", str(p.get("waveA", 0.4)), "--waveT", str(p.get("waveT", 0.9))]
        if sc == "ship":
            args += ["--shipsz", str(p.get("shipsz", 1.0))]
    _ensure(_bin("sph", "sph2d"))
    pr(f"SPH · {p.get('scene', 'Dam break')} · dp={dp:.3f}…")
    subprocess.run(args, check=True, env=_ENV)
    n = _nframes(tmp); skip = max(1, n // 100); idx = list(range(0, n, skip))
    raw = [np.fromfile(Path(tmp) / f"frame_{i:05d}.bin", dtype=np.float32).reshape(-1, 3) for i in idx]
    hints = {"Lx": Lx, "Ly": Ly, "dp": dp, "vmax": 1.2 * np.sqrt(2 * g * max(H, Ly * 0.5))}
    if sc == "ship":
        hints["hull"] = [np.fromfile(Path(tmp) / f"hull_{i:05d}.bin", dtype=np.float32).reshape(-1, 2)
                         for i in idx]
    return Result("particles", raw, f"{p.get('scene', 'Dam break')}  ({len(raw[-1])} particles)",
                  hints=hints)


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
    "Wind Tunnel": {
        "params": [{"name": "obstacle", "label": "Obstacle", "type": "choice", "group": "Geometry",
                    "choices": ["Cylinder", "Square", "Diamond", "Airfoil", "Your text"],
                    "default": "Cylinder",
                    "help": "What to drop into the stream — a shape, or your own text."},
                   {"name": "text", "label": "Your text", "type": "str", "default": "FlowZoo",
                    "group": "Geometry", "help": "Used when Obstacle = 'Your text'. Short words read best."},
                   _f("size", "Obstacle size (frac.)", 0.13, 0.05, 0.30, "Geometry",
                      "Obstacle size as a fraction of the channel height. Bigger → larger, "
                      "slower-shedding wake."),
                   _f("angle", "Airfoil angle (°)", 12, 0, 25, "Geometry",
                      "Angle of attack for the Airfoil obstacle (degrees) — ignored otherwise."),
                   _f("reynolds", "Reynolds number", 160, 60, 1200, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_windtunnel(p, pr, t)},
    "Rising Smoke": {
        "params": [_f("buoyancy", "Buoyancy", 2.5e-3, 5e-4, 6e-3, "Physics", _H["buoy"]),
                   _f("confinement", "Vorticity confinement", 8, 0, 20, "Physics", _H["conf"]),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"]),
                   _f("source", "Source width (×)", 1.0, 0.3, 3.0, "Geometry",
                      "Width of the hot source at the floor."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("smoke", p, pr, t)},
    "Mushroom Clouds": {
        "params": [_f("atwood", "Atwood number", 0.7, 0.2, 1.0, "Physics",
                      "A = (ρ_heavy − ρ_light)/(ρ_heavy + ρ_light), the density contrast across "
                      "the interface. It sets how hard the heavy fluid falls: higher A → faster, "
                      "narrower spikes and more vigorous mushroom roll-up."),
                   _f("gravity", "Gravity", 1.2e-3, 4e-4, 3e-3, "Physics", _H["grav"]),
                   _f("viscosity", "Viscosity", 1.5e-4, 3e-5, 5e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Interface ripple (×)", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the initial interface ripple that seeds the fingers."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rt", p, pr, t)},
    "Detonation": {
        "params": [{"name": "scene", "label": "Scene", "type": "choice", "group": "Geometry",
                    "choices": ["Open air", "Shock hits a city"], "default": "Open air",
                    "help": "Open air: a free blast wave expanding into still gas. Shock hits a "
                    "city: a ground burst whose blast diffracts around and reflects off two solid "
                    "towers — watch the Mach stems and shadow zones behind the buildings."},
                   _f("pressure", "Blast pressure", 10.0, 2.0, 40.0, "Physics",
                      "Pressure inside the charge. Higher → a stronger, faster shock."),
                   _f("charge", "Charge size (frac.)", 0.06, 0.02, 0.18, "Geometry",
                      "Radius of the high-pressure charge as a fraction of the domain width."),
                   _when(_f("strength", "Structure strength", 1.0, 0.2, 3.0, "Physics",
                            "How much overpressure each block of the towers can take before it "
                            "fails. Weak structures (low) are scoured away windward-first and "
                            "collapse; strong ones (high) shrug off the blast. Failed blocks turn "
                            "to flying debris, so the towers visibly change shape as the shock hits."),
                         "scene", ["Shock hits a city"]),
                   _f("debris", "Debris particles", 200, 0, 800, "Render",
                      "Glowing debris scattered across the domain and swept outward by the "
                      "blast (visual only)."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("blast", p, pr, t)},
    "Shockwave Strike": {
        "params": [{"name": "target", "label": "Target", "type": "choice", "group": "Geometry",
                    "choices": ["Single bubble", "Two bubbles"], "default": "Single bubble",
                    "help": "One gas bubble, or two stacked bubbles whose roll-ups interact."},
                   _f("mach", "Shock Mach number", 1.5, 1.1, 3.0, "Physics",
                      "Strength of the incoming shock, M_s = (shock speed)/(sound speed). The "
                      "post-shock gas state is set from the exact Rankine–Hugoniot relations, so "
                      "higher M → stronger compression, hotter gas and a faster, tighter roll-up."),
                   _f("densratio", "Density ratio ρ_bub/ρ_air", 0.18, 0.05, 4.0, "Physics",
                      "Bubble density ÷ ambient air density. <1 = a light bubble (the shock "
                      "accelerates through it and it rolls up fast); >1 = a heavy bubble (the "
                      "shock slows and focuses inside it). This is the Atwood-number analogue that "
                      "sets the sign and strength of the baroclinic vorticity."),
                   _f("bubble", "Bubble size (frac.)", 0.18, 0.08, 0.32, "Geometry",
                      "Bubble radius as a fraction of the domain height."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_euler("bubble", p, pr, t)},
    "The Big Splash": {
        "params": [{"name": "scene", "label": "Scene", "type": "choice", "group": "Geometry",
                    "choices": ["Dam break", "Drop & splash", "Sloshing tank",
                                "Pour into a glass", "Wavy ocean", "Ship on waves"],
                    "default": "Dam break",
                    "help": "Which free-surface scenario to run. Each scene exposes its own "
                    "controls below."},
                   # --- dam break ---
                   _when(_f("width", "Dam width (m)", 1.0, 0.4, 2.0, "Geometry",
                            "Width of the held-back water column."), "scene", ["Dam break"]),
                   _when(_f("height", "Dam height (m)", 2.0, 0.6, 3.0, "Geometry",
                            "Height of the column — more head → a faster, taller surge."),
                         "scene", ["Dam break"]),
                   # --- drop & splash ---
                   _when(_f("dropsize", "Drop size (m)", 1.0, 0.4, 1.8, "Geometry",
                            "Width of the falling block of water."), "scene", ["Drop & splash"]),
                   _when(_f("dropheight", "Release height (frac.)", 0.70, 0.45, 0.92, "Geometry",
                            "How high the block starts, as a fraction of tank height. Higher → "
                            "faster impact and a bigger crown."), "scene", ["Drop & splash"]),
                   # --- sloshing tank ---
                   _when(_f("sloshA", "Slosh strength (×g)", 0.7, 0.1, 1.5, "Physics",
                            "Amplitude of the oscillating sideways gravity, as a multiple of g."),
                         "scene", ["Sloshing tank"]),
                   _when(_f("sloshT", "Slosh period (s)", 1.1, 0.5, 3.0, "Physics",
                            "Period of the side-to-side forcing. Near the tank's natural period "
                            "the wave resonates and breaks."), "scene", ["Sloshing tank"]),
                   # --- pour into a glass ---
                   _when(_f("spout", "Spout width (frac.)", 0.045, 0.02, 0.12, "Geometry",
                            "Width of the pour stream as a fraction of the tank width."),
                         "scene", ["Pour into a glass"]),
                   _when(_f("pourv", "Pour speed (m/s)", 2.2, 0.5, 5.0, "Physics",
                            "Speed the water leaves the spout. Faster → more splashing on impact."),
                         "scene", ["Pour into a glass"]),
                   # --- wavy ocean / ship ---
                   _when(_f("waveA", "Wave height (m)", 0.4, 0.1, 0.9, "Physics",
                            "Stroke of the wavemaker paddle — sets the wave amplitude."),
                         "scene", ["Wavy ocean", "Ship on waves"]),
                   _when(_f("waveT", "Wave period (s)", 0.9, 0.4, 2.0, "Physics",
                            "Period of the wavemaker — sets the wavelength of the train."),
                         "scene", ["Wavy ocean", "Ship on waves"]),
                   _when(_f("shipsz", "Ship size (×)", 1.0, 0.5, 1.8, "Geometry",
                            "Scale of the floating hull. Bigger ships sit deeper and roll slower."),
                         "scene", ["Ship on waves"]),
                   # --- common ---
                   _f("particles", "Particles (≈)", 3000, 600, 12000, "Geometry",
                      "Approximate number of SPH particles. More → finer splash, slower."),
                   _f("gravity", "Gravity (m/s²)", 9.81, 1.0, 25.0, "Physics",
                      "Gravitational acceleration."),
                   P_DUR()],
        "solve": lambda p, pr, t: _solve_dam(p, pr, t)},
    "Cloud Billows": {
        "params": [_f("viscosity", "Viscosity", 8e-5, 1e-5, 4e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Shear perturbation", 0.05, 0.005, 0.2, "Physics",
                      "Strength of the initial shear-layer kick that seeds the billows."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_spectral(p, pr, t)},
}

_LBM_EQ = r"$f_q(\mathbf{x}+\mathbf{c}_q,\,t{+}1)=f_q(\mathbf{x},t)-\dfrac{1}{\tau}\,(f_q-f_q^{\rm eq})$"
_EULER_EQ = r"$\partial_t\mathbf{U}+\nabla\!\cdot\!\mathbf{F}(\mathbf{U})=0,\quad \mathbf{U}=[\rho,\ \rho u,\ \rho v,\ E]$"

META = {
    "Wind Tunnel": {"method": "Flow past an obstacle · Lattice-Boltzmann (D2Q9)",
        "blurb": "Drop something into a steady stream and watch the wake. Past a critical "
                 "Reynolds number the flow can no longer stay attached: it separates, sheds "
                 "vortices alternately from each side, and trails the famous von Kármán "
                 "vortex street — the same wake that sings in wires and shakes chimneys, "
                 "bridge decks and offshore risers. Choose a cylinder, a square, a diamond, "
                 "an angled airfoil, or even your own name, and see how the shape rewrites "
                 "the wake.",
        "eq": _LBM_EQ,
        "numerics": "Solved with a D2Q9 lattice-Boltzmann method: nine discrete velocities "
                    "per cell, a single-relaxation-time (BGK) collision toward the local "
                    "equilibrium, and a streaming step that shifts populations to neighbours. "
                    "The obstacle — any shape or text — is simply a set of cells flagged solid "
                    "and handled by half-way bounce-back (a no-slip wall), so no mesh is ever "
                    "generated. Velocity inlet, open outflow, periodic top/bottom; the "
                    "relaxation time τ sets the viscosity via ν = (τ − ½)/3, hence the Reynolds number.",
        "validation": "The dimensionless shedding frequency — the Strouhal number St = fD/U — "
                       "comes out ≈ 0.20 for a cylinder at Re ≈ 160, matching the long-"
                       "established experimental value of about 0.2 across Re ≈ 100–300.",
        "demo": "results/flow_around_flowzoo.gif"},
    "Rising Smoke": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "A continuous source of hot, dyed fluid is injected at the floor. Because it "
                 "is lighter than its surroundings, buoyancy drives it upward; as it rises it "
                 "shears against the still air, rolls up into vortices, and breaks into the "
                 "turbulent, billowing column we recognise as smoke. This is the canonical "
                 "buoyancy-driven incompressible flow, and the same machinery underlies "
                 "visual-effects smoke, plume dispersion and indoor-air modelling.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f}_b,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "A projection ('stable fluids') method: unconditionally-stable "
                    "semi-Lagrangian advection, a red-black Gauss–Seidel SOR solve of the "
                    "pressure-Poisson equation to enforce ∇·u = 0, a Boussinesq buoyancy "
                    "force proportional to the transported temperature/dye, and vorticity "
                    "confinement that re-injects the fine swirls numerical diffusion erodes.",
        "validation": "The velocity field is kept divergence-free to the projection "
                       "tolerance each step; buoyant transport stays stable and the plume "
                       "develops the expected shear roll-up.",
        "demo": "results/smoke_plume.gif"},
    "Mushroom Clouds": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "Place a heavy fluid on top of a lighter one in a gravitational field and "
                 "the arrangement is unstable: the tiniest ripple on the interface grows, the "
                 "heavy fluid sinks in falling spikes while the light fluid rises in bubbles, "
                 "and each finger curls into the classic mushroom cap. The Rayleigh–Taylor "
                 "instability governs phenomena from supernova remnants and inertial-"
                 "confinement fusion to salt domes and atmospheric mixing.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}-g\,\rho\,\hat{\mathbf{y}},\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The same incompressible projection solver, with an advected density "
                    "field whose weight drives the gravitational body force. The interface is "
                    "seeded with a small multi-mode ripple; growth rate is controlled by the "
                    "gravity and viscosity you set.",
        "validation": "Reproduces the characteristic spike-and-bubble mushroom roll-up; the "
                       "finger growth scales with gravity and is damped by viscosity as theory predicts.",
        "demo": "results/rayleigh_taylor.gif"},
    "Detonation": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A small region of very high pressure is released into ambient gas. It "
                 "bursts outward as a near-circular shock wave — a thin front across which "
                 "density, pressure and velocity jump almost discontinuously — trailed by an "
                 "expansion that leaves a low-density cavity behind. This is the textbook "
                 "blast-wave problem at the heart of explosion safety, astrophysical "
                 "shockwaves and supersonic aerodynamics; here glowing debris is scattered "
                 "through the domain and swept up as the front passes.",
        "eq": _EULER_EQ,
        "numerics": "A finite-volume solver for the compressible Euler equations: "
                    "piecewise-linear MUSCL reconstruction with a minmod slope limiter, an "
                    "HLLC approximate Riemann solver at each cell face, and a two-stage "
                    "strong-stability-preserving Runge–Kutta time step under a CFL condition "
                    "(γ = 1.4). Schlieren imaging shows |∇ρ|, lighting up the shock fronts. In "
                    "the city scene, solid blocks are held as reflecting walls and fail when the "
                    "overpressure on an exposed face exceeds their strength — an overpressure-"
                    "driven fluid–structure coupling that lets the towers crumble into debris.",
        "validation": "The identical solver reproduces the exact Sod shock-tube Riemann "
                       "solution to a mean density error of ≈ 0.002 — capturing the "
                       "rarefaction, contact and shock crisply.",
        "demo": "results/explosion.gif"},
    "Shockwave Strike": {"method": "Compressible Euler · finite-volume HLLC",
        "blurb": "A planar shock wave travels through air and strikes a bubble of lighter "
                 "gas. Because the shock speeds up in the light gas, it bends and focuses, "
                 "and the misalignment of pressure and density gradients deposits vorticity "
                 "on the interface (the baroclinic mechanism) — rolling the bubble up into a "
                 "vortex pair. This shock-bubble / Richtmyer–Meshkov interaction is a key "
                 "model problem for supersonic mixing and inertial-confinement fusion.",
        "eq": _EULER_EQ,
        "numerics": "Same compressible finite-volume scheme (MUSCL + minmod, HLLC Riemann "
                    "solver, SSP-RK2, γ = 1.4). One or two circular bubbles of a chosen "
                    "density ratio sit in still air; the incoming flow is the exact "
                    "Rankine–Hugoniot post-shock state for the Mach number you set, so shock "
                    "strength and density contrast are both physical, tunable inputs.",
        "validation": "Uses the same HLLC solver validated against the exact Sod shock tube "
                       "(mean density error ≈ 0.002).",
        "demo": "results/shock_bubble.gif"},
    "The Big Splash": {"method": "Free-surface water · Smoothed-Particle Hydrodynamics",
        "blurb": "Water you can actually splash — six scenes from one meshfree solver. "
                 "Break a dam and watch the surge overturn against the far wall; drop a block "
                 "into a pool for a crown splash; slosh a tank back and forth until it "
                 "breaks; pour a stream into a tall glass; drive a wavemaker across an "
                 "ocean of travelling waves; or float a rigid ship on them. There is no grid "
                 "at all — the fluid is a cloud of moving particles, which is why it handles "
                 "violent free surfaces and breaking, folding water so naturally.",
        "eq": r"$\dfrac{D\mathbf{v}_i}{Dt}=-\sum_j m_j\!\left(\dfrac{p_i}{\rho_i^2}+\dfrac{p_j}{\rho_j^2}+\Pi_{ij}\right)\nabla W_{ij}+\mathbf{g}$",
        "numerics": "Weakly-compressible SPH: each particle carries mass and velocity; "
                    "density and forces are smoothed sums over neighbours using a cubic-"
                    "spline kernel. Pressure follows a stiff Tait equation of state (clamped "
                    "≥ 0 to avoid the free-surface tensile instability), with Monaghan "
                    "artificial viscosity and a uniform background grid for fast neighbour "
                    "search. The walls are dynamic boundary particles — fixed layers of "
                    "particles that develop pressure through the same equation of state when "
                    "the fluid presses on them, so the wall pushes back with real pressure "
                    "(no penalty force on the fluid, no spurious near-wall motion); the "
                    "wavemaker is simply a wall layer that moves. A δ-SPH density-diffusion "
                    "term and XSPH velocity smoothing damp the acoustic noise and relax the "
                    "initial lattice so the fluid starts genuinely at rest; the floating ship "
                    "is a rigid body whose heave, surge and roll are driven by the pressure "
                    "the water exerts on its hull.",
        "validation": "The leading surge-front advances at a speed within the physical range "
                       "of the frictionless Ritter dry-bed limit 2√(gH) — the column must "
                       "first collapse vertically, so the real front lags that ideal bound.",
        "demo": "results/dam_break.gif"},
    "Cloud Billows": {"method": "Pseudo-spectral · FFT",
        "blurb": "Two fluid streams sliding past each other at different speeds form an "
                 "unstable shear layer: ripples on the interface grow and roll up into a row "
                 "of spiral 'billows' that pair and merge, cascading toward two-dimensional "
                 "turbulence. The Kelvin–Helmholtz instability paints the billow clouds in "
                 "the sky, the bands of Jupiter, and the mixing layers in oceans and "
                 "engines. It is solved here with a high-accuracy spectral method.",
        "eq": r"$\partial_t\omega+(\mathbf{u}\!\cdot\!\nabla)\omega=\nu\nabla^2\omega,\qquad \nabla^2\psi=-\omega$",
        "numerics": "A pseudo-spectral vorticity–streamfunction formulation on a periodic "
                    "box: every spatial derivative is taken in Fourier space via the FFT, the "
                    "nonlinear advection term is formed in physical space with 2/3-rule "
                    "dealiasing, and time advances with classical fourth-order Runge–Kutta "
                    "(stable for the advection operator's imaginary eigenvalues).",
        "validation": "With viscosity switched off the scheme conserves kinetic energy to "
                       "≈ 1.5×10⁻⁷ over hundreds of steps — the hallmark of spectral accuracy.",
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
