"""Funoos engine: solve an exhibit, then render any visualization on demand.

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
         "particles": ["Particles", "Foam & spray", "Speed field"],
         "porous": ["Speed", "Streamlines", "Vorticity"],
         "field": ["Pattern"],
         "quantum": ["Probability |ψ|²", "Phase"]}
DEFCMAP = {"lbm": "Curl (cyan–amber)", "spectral": "Curl (cyan–amber)",
           "density": "Ember (fire)", "ns": "Ember (fire)", "particles": "Ocean (water)",
           "porous": "Turbo", "field": "Inferno", "quantum": "Magma"}


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
        if self.kind in ("lbm", "spectral", "porous"):
            return self._render_vel(self.raw, view, cm, self.mask)
        if self.kind == "density":
            return self._render_density(view, cm)
        if self.kind == "ns":
            if view == "Dye":
                v0, v1 = self.hints["vlim"]
                return [render.add_colorbar(
                    render.field_to_rgb(s, cm, v0, v1, upscale=1, gamma=self.hints["gamma"],
                                        mask=self.mask, mask_color="#6e6358"),
                    cm, v0, v1, self.hints.get("label", "")) for s in self.raw]
            return self._render_vel(self.hints["vel"], view, cm, None)
        if self.kind == "particles":
            if view == "Speed field":
                return self._render_sph_field(cm)
            return self._render_particles(cm, foam=(view == "Foam & spray"))
        if self.kind == "field":
            v1 = np.percentile(self.raw[-1], 99.0) + 1e-9
            return [render.add_colorbar(render.field_to_rgb(s, cm, 0, v1, upscale=2),
                                        cm, 0, v1, self.hints.get("label", "")) for s in self.raw]
        if self.kind == "quantum":
            return self._render_quantum(view, cm)

    def _render_quantum(self, view, cm):
        import matplotlib.cm as mcm
        out = []
        pmax = np.percentile(self.raw[-1], 99.7) + 1e-12
        if view == "Phase":
            twil = mcm.get_cmap("twilight")
            for prob, ph in zip(self.raw, self.hints["phase"]):
                hue = twil((ph + np.pi) / (2 * np.pi))[..., :3]      # cyclic phase → color
                val = np.clip(prob / pmax, 0, 1)[..., None]          # brightness ∝ |ψ|²
                rgb = (hue * val * 255).astype(np.uint8)
                out.append(render.add_colorbar(np.flipud(rgb), cm, -np.pi, np.pi, "arg ψ"))
            return out
        return [render.add_colorbar(render.field_to_rgb(p, cm, 0, pmax, upscale=2),
                                    cm, 0, pmax, "|ψ|²") for p in self.raw]

    def _render_vel(self, vel, view, cm, mask):
        pct = 80.0 if self.kind == "porous" else 99.5   # porous flow is slow/sparse → brighten
        if view == "Streamlines":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in vel]
            vmax = np.percentile(sp[-1], pct) + 1e-12
            return [render.add_colorbar(
                render.streamlines_rgb(ux, uy, cmap=cm, mask=mask, vmax=vmax),
                cm, 0, vmax, "|u|") for ux, uy in vel]
        if view == "Speed":
            sp = [np.sqrt(ux * ux + uy * uy) for ux, uy in vel]
            vmax = np.percentile(sp[-1], pct) + 1e-12
            g = 0.45 if self.kind == "porous" else 1.0          # brighten the slow pore flow
            mc = "#0f1830" if self.kind == "porous" else render.SOLID   # dark grains so flow pops
            return [render.add_colorbar(
                render.field_to_rgb(s, cm, 0, vmax, mask=mask, mask_color=mc,
                                    upscale=1, gamma=g), cm, 0, vmax, "|u|") for s in sp]
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
        PSIZE = float(np.clip((diam_pt * 1.35) ** 2, 5.0, 230.0))  # high cap so a fine glass reads as continuous water
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
    elif obs == "F1 car":
        L = ny * 1.05; cx = int(nx * 0.30)
        mask = geometry.f1_car(nx, ny, cx, L); D = 0.34 * L; probe = cx + int(2.4 * L)
    elif obs == "Cyclist":
        S = ny * 0.42; cx = int(nx * 0.24)
        mask = geometry.cyclist(nx, ny, cx, S, riders=1); D = 0.6 * S; probe = cx + int(3 * S)
    elif obs == "Peloton (drafting)":
        S = ny * 0.38; cx = int(nx * 0.28)
        mask = geometry.cyclist(nx, ny, cx, S, riders=2, gap=1.0); D = 0.6 * S; probe = cx + int(3 * S)
    else:                                                   # Cylinder
        mask = geometry.cylinder(nx, ny, cx, cy, D / 2); probe = cx + int(3 * D)
    tau = 0.5 + 3 * (U * D / Re)
    probe = int(min(probe, 0.85 * nx))                      # keep the probe clear of the outlet sponge (last 12%)
    _ys = np.where(mask.any(axis=1))[0]                      # sample the wake at the body's height
    probe_y = int(round(_ys.mean())) if len(_ys) else ny // 2
    probe_y = int(np.clip(probe_y, 2, ny - 3))
    if obs in ("F1 car", "Cyclist", "Peloton (drafting)"):  # a real no-slip road under the vehicle
        mask[0:max(2, ny // 28), :] = 1                     # (otherwise periodic walls let flow wrap under)
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    _ensure(_bin("lbm", "lbm2d"))
    steps = int(44000 * _durv(p))
    pr(f"LBM wind tunnel · {obs} · {nx}×{ny}, Re={Re:.0f}, {steps} steps…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--U", str(U), "--tau", f"{tau:.5f}",
                    "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp, "--probe_x", str(min(probe, nx - 2)), "--probe_y", str(probe_y)],
                   check=True, env=_ENV)
    save_every = max(1, steps // 120)
    n = _nframes(tmp); stride = max(1, (n - n // 5) // 90)
    use = range(n // 5, n, stride)
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    hints = {"probe_x": min(probe, nx - 2), "probe_y": probe_y, "D": D, "U": U,
             "obstacle": obs,                            # so diagnostics can pick the right plot
             "frame_dt_steps": stride * save_every}     # for the lift / Strouhal diagnostic
    return Result("lbm", raw, f"wind tunnel · {obs} · Re={Re:.0f} · {nx}×{ny}",
                  mask=mask, hints=hints)


def _solve_porous(p, pr, tmp):
    s = _res(p); nx, ny = int(380 * s), int(360 * s)
    phi = float(p["porosity"]); grain = max(4, int(float(p["grain"]) * ny))
    mask = geometry.porous(nx, ny, solid_frac=1.0 - phi, grain=grain, seed=int(p.get("seed", 1)))
    geometry.save_mask(mask, Path(tmp) / "m.bin")
    _ensure(_bin("lbm", "lbm2d"))
    tau, force = 0.8, 1.2e-5            # viscous (Stokes regime → Darcy valid), gentle body force
    steps = int(24000 * _durv(p))
    pr(f"LBM porous medium · φ={phi:.2f} · {nx}×{ny}…")
    subprocess.run([str(_bin("lbm", "lbm2d")), "--nx", str(nx), "--ny", str(ny),
                    "--mask", str(Path(tmp) / "m.bin"), "--periodic", "1", "--force", str(force),
                    "--tau", str(tau), "--steps", str(steps), "--save_every", str(max(1, steps // 120)),
                    "--out", tmp], check=True, env=_ENV)
    n = _nframes(tmp); use = range(n // 3, n, max(1, (n - n // 3) // 70))
    raw = [_read_vel(tmp, i, nx, ny) for i in use]
    meta = {}
    for line in (Path(tmp) / "meta.txt").read_text().splitlines():
        kk = line.split()
        if len(kk) == 2:
            try: meta[kk[0]] = float(kk[1])
            except ValueError: pass
    poro = meta.get("porosity", phi); perm = meta.get("permeability", 0.0)
    hints = {"porosity": poro, "permeability": perm, "grain": grain, "force": force}
    return Result("porous", raw, f"porous · φ={poro:.2f} · k={perm:.2e}", mask=mask, hints=hints)


def _solve_ns(mode, p, pr, tmp):
    s = _res(p); steps = int(4800 * _durv(p))
    if mode in ("smoke", "rt"):
        nx, ny = int(280 * s), int(440 * s)         # tall box for rising plumes / fingers
    elif mode == "rb":
        nx, ny = int(480 * s), int(230 * s)         # wide, shallow cell for convection rolls
    elif mode == "flame":
        nx, ny = int(190 * s), int(360 * s)         # tall, narrow box for a slender candle flame
    else:                                           # wind
        nx, ny = int(540 * s), int(420 * s)         # tall, wide box: open top, the plume rises & blows across
    _ensure(_bin("incompressible", "ins2d"))
    args = [str(_bin("incompressible", "ins2d")), "--mode", mode, "--nx", str(nx),
            "--ny", str(ny), "--steps", str(steps), "--save_every", str(max(1, steps // 110)),
            "--out", tmp, "--visc", str(p["viscosity"])]
    if mode == "smoke":
        args += ["--buoy", str(p["buoyancy"]), "--conf", str(p["confinement"]), "--srcw", str(p["source"]),
                 "--flicker", str(p.get("flicker", 0.0))]
        hints = {"vlim": (0.0, 0.85), "gamma": 0.85, "label": "smoke density"}
    elif mode == "rt":
        args += ["--grav", str(p["gravity"]), "--pert", str(p["perturbation"]), "--conf", "0",
                 "--iters", "80", "--atwood", str(p.get("atwood", 1.0))]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "density ρ"}
    elif mode == "rb":
        args += ["--buoy", str(p["buoyancy"]), "--conf", "0", "--iters", "80",
                 "--pert", str(p.get("perturbation", 1.0))]
        hints = {"vlim": (0.0, 1.0), "gamma": 1.0, "label": "temperature T"}
    elif mode == "flame":                           # laminar diffusion flame (Burke–Schumann)
        args += ["--buoy", str(p["buoyancy"]), "--zst", str(p.get("zst", 0.12)),
                 "--conf", str(p["confinement"]), "--srcw", str(p["source"]), "--visc", str(p["viscosity"])]
        hints = {"vlim": (0.0, 1.0), "gamma": 0.6, "label": "flame temperature T"}
    else:                                           # wind — chimney plume in a crosswind
        args += ["--buoy", str(p["buoyancy"]), "--wind", str(p["wind"]),
                 "--conf", str(p["confinement"]), "--srcw", str(p["source"])]
        hints = {"vlim": (0.0, 0.85), "gamma": 0.85, "label": "smoke density"}
    pr(f"Navier–Stokes ({mode}) {nx}×{ny}, {steps} steps…")
    subprocess.run(args, check=True, env=_ENV)
    n = _nframes(tmp); skip = max(1, n // 100); idx = list(range(0, n, skip))
    raw = [_read_scalar(tmp, i, nx, ny) for i in idx]

    def _rv(i):                                              # read the vel_*.bin field
        b = np.fromfile(Path(tmp) / f"vel_{i:05d}.bin", dtype=np.float32)
        return b[: nx * ny].reshape(ny, nx).copy(), b[nx * ny:].reshape(ny, nx).copy()
    hints["vel"] = [_rv(i) for i in idx]                     # for Speed/Vorticity/Streamlines
    hints["ns_mode"] = mode                                  # so diagnostics can pick the right plot
    mask = None
    if mode == "wind":                                       # draw the solid chimney stack
        stack_h = int(0.32 * ny); sxx = nx // 4
        sw = max(6, int(nx / 12 * float(p["source"]))); hw = max(2, sw // 2)
        mask = np.zeros((ny, nx), np.uint8)
        mask[0:stack_h, max(0, sxx - hw):min(nx, sxx + hw + 1)] = 1
    return Result("ns", raw, f"{mode}  {nx}×{ny}", hints=hints, mask=mask)


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
                "pour": (0.13, 0.20), "waves": (6.0, 2.4), "ship": (6.0, 2.4)}   # pour = a real glass


def _solve_dam(p, pr, tmp):
    sc = _SPLASH_SCENE.get(p.get("scene", "Dam break"), "dam")
    Lx, Ly = _SPLASH_TANK[sc]
    a = float(p.get("dropsize", 0.4)) if sc == "drop" else float(p["width"])
    g = float(p["gravity"])
    npart = max(500.0, float(p["particles"]))
    if sc == "pour":                          # a glass: scale sound speed to the glass, resolve its width
        H = Ly; dp = Lx / 44.0; tend = 3.0 * _durv(p)
    else:
        H = float(p["height"]); dp = float(np.clip(np.sqrt(Lx * Ly * 0.4 / npart), 0.02, 0.08))
        tend = 2.0 * _durv(p)
    c0 = 10.0 * (g * max(H, Ly * 0.5)) ** 0.5         # solver's sound speed (for frame cadence)
    steps_est = tend / (0.08 * 1.3 * dp / c0)
    save_every = max(20, int(steps_est // 120))       # ~120 frames whatever the scene scale
    args = [str(_bin("sph", "sph2d")), "--scene", sc, "--a", str(a), "--H", str(H),
            "--Lx", str(Lx), "--Ly", str(Ly), "--dp", str(dp), "--g", str(g),
            "--tend", str(tend), "--save_every", str(save_every), "--out", tmp]
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
    if sc == "pour":          # colour by the pour/impact speed, not a dam-height scale
        vmax = 1.3 * max(float(p.get("pourv", 1.4)), float(np.sqrt(2 * g * Ly)))
    else:
        vmax = 1.2 * float(np.sqrt(2 * g * max(H, Ly * 0.5)))
    hints = {"Lx": Lx, "Ly": Ly, "dp": dp, "vmax": vmax}
    if sc == "ship":
        hints["hull"] = [np.fromfile(Path(tmp) / f"hull_{i:05d}.bin", dtype=np.float32).reshape(-1, 2)
                         for i in idx]
    return Result("particles", raw, f"{p.get('scene', 'Dam break')}  ({len(raw[-1])} particles)",
                  hints=hints)


def _solve_spectral(p, pr, tmp):
    from .spectral import Spectral2D, double_shear_layer, random_field
    s = _res(p); n = int(256 * s); steps = int(2800 * _durv(p)); nu = float(p["viscosity"])
    sim = Spectral2D(n=n, nu=nu)
    if p.get("init") == "Random turbulence":
        wh = random_field(n, seed=1); label = "decaying turbulence"
    else:
        wh = double_shear_layer(n, amp=float(p["perturbation"])); label = "Kelvin–Helmholtz"
    dt = 0.4 * (2 * np.pi / n)
    pr(f"spectral {n}×{n}, ν={nu:.1e}, {steps} steps…")
    vel = []
    for st in range(steps + 1):
        if st % max(1, steps // 90) == 0:
            vel.append(sim.velocity(wh))
        wh = sim.step(wh, dt)
    return Result("spectral", vel, f"{label}  {n}×{n}")


def _solve_mixing(p, pr, tmp):
    from .spectral import Spectral2D, random_field, advect_sl
    s = _res(p); n = int(256 * s); steps = int(2600 * _durv(p)); nu = 4e-4
    sim = Spectral2D(n=n, nu=nu); wh = random_field(n, seed=3); dt = 0.4 * (2 * np.pi / n)
    L = 2 * np.pi
    # dye: alternating horizontal bands (so stirring shows the folding/filamentation)
    yy = np.linspace(0, L, n, endpoint=False)[None, :] * np.ones((n, 1))
    c = 0.5 * (1 + np.sign(np.sin(float(p.get("bands", 6)) * yy)))
    kap = float(p.get("diffusion", 1e-4))
    pr(f"chaotic mixing {n}×{n}, {steps} steps…")
    raw = []
    for st in range(steps + 1):
        u, v = sim.velocity(wh)
        if st % max(1, steps // 100) == 0:
            raw.append(c.copy())
        c = advect_sl(c, u, v, dt, L)
        if kap > 0:                                   # gentle scalar diffusion (spectral)
            c = np.real(np.fft.ifft2(np.exp(-kap * sim.k2 * dt) * np.fft.fft2(c)))
        wh = sim.step(wh, dt)
    return Result("field", raw, f"chaotic mixing  {n}×{n}", hints={"label": "dye"})


def _solve_reaction(p, pr, tmp):
    from .reaction import gray_scott, PRESETS
    s = _res(p); n = int(220 * s)
    pat = p.get("pattern", "Spots"); F, k = PRESETS.get(pat, (0.035, 0.065))
    steps = int(9000 * _durv(p))
    pr(f"Gray–Scott {n}×{n}, {pat} (F={F:.4f}, k={k:.4f}), {steps} steps…")
    frames = gray_scott(n=n, F=F, k=k, steps=steps, nframes=110, seed=1)
    return Result("field", frames, f"{pat}  {n}×{n}", hints={"label": "V concentration"})


def _solve_quantum(p, pr, tmp):
    from .quantum import simulate
    s = _res(p); n = int(220 * s); steps = int(360 * _durv(p))
    scene = {"Free spreading": "free", "Tunnelling barrier": "barrier",
             "Double slit": "slit", "Harmonic well": "harmonic"}.get(p.get("scene", "Tunnelling barrier"), "barrier")
    pr(f"Schrödinger {n}×{n} ({scene}), {steps} steps…")
    prob, phase, V, norm = simulate(n=n, scene=scene, steps=steps, nframes=110,
                                    k0=float(p.get("momentum", 360)), width=float(p.get("width", 0.06)),
                                    v0=float(p.get("barrier", 320)))
    if scene == "harmonic":          # closed system → unitarity check
        info = f"harmonic well  {n}×{n} · norm conserved to {max(abs(x - 1) for x in norm):.0e}"
    else:                            # open: the absorbing border removes escaping probability
        info = f"{scene}  {n}×{n} · absorbing boundary"
    return Result("quantum", prob, info, hints={"phase": phase, "norm": norm, "scene": scene})


EXHIBITS = {
    "Wind Tunnel": {
        "params": [{"name": "obstacle", "label": "Obstacle", "type": "choice", "group": "Geometry",
                    "choices": ["Cylinder", "Square", "Diamond", "Airfoil",
                                "F1 car", "Cyclist", "Peloton (drafting)", "Your text"],
                    "default": "Cylinder",
                    "help": "What to drop into the stream — a shape, a vehicle, or your own text."},
                   _when({"name": "text", "label": "Your text", "type": "str", "default": "Funoos",
                          "group": "Geometry", "help": "The word to drop into the stream. Short words read best."},
                         "obstacle", ["Your text"]),
                   _f("size", "Obstacle size (frac.)", 0.13, 0.05, 0.30, "Geometry",
                      "Obstacle size as a fraction of the channel height. Bigger → larger, "
                      "slower-shedding wake."),
                   _when(_f("angle", "Airfoil angle (°)", 12, 0, 25, "Geometry",
                            "Angle of attack of the airfoil, in degrees."), "obstacle", ["Airfoil"]),
                   _f("reynolds", "Reynolds number", 160, 60, 1200, "Physics", _H["Re"]),
                   _f("speed", "Inflow speed (lattice)", 0.08, 0.02, 0.15, "Physics", _H["U"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_windtunnel(p, pr, t)},
    "Rising Smoke": {
        "params": [_f("buoyancy", "Buoyancy", 2.5e-3, 5e-4, 6e-3, "Physics", _H["buoy"]),
                   _f("confinement", "Vorticity confinement", 8, 0, 20, "Physics", _H["conf"]),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"]),
                   _f("flicker", "Flame flicker", 0.0, 0.0, 1.0, "Physics",
                      "Wobble & pulse the source so the plume dances like a flame. 0 = a steady "
                      "column; 1 = a lively candle flame."),
                   _f("source", "Source width (×)", 1.0, 0.3, 3.0, "Geometry",
                      "Width of the hot source at the floor."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("smoke", p, pr, t)},
    "Candle Flame": {
        "params": [_f("buoyancy", "Heat-release buoyancy", 0.020, 0.008, 0.03, "Physics",
                      "How strongly the heat released at the flame sheet lifts the gas. Stronger "
                      "buoyancy draws the fuel up faster, keeping the flame slender and steady."),
                   _f("zst", "Stoichiometric mixture  Z_st", 0.18, 0.08, 0.30, "Physics",
                      "The fuel/air ratio at which the flame burns. The luminous sheet sits on the "
                      "Z = Z_st surface; a larger value pulls it tighter to the fuel core (a thinner flame)."),
                   _f("source", "Wick width (×)", 0.45, 0.3, 1.5, "Geometry",
                      "Width of the fuel vapour leaving the wick. A thin wick gives a slender candle flame."),
                   _f("confinement", "Vorticity confinement", 4, 0, 20, "Physics",
                      "Sharpens the small eddies that make the flame tip lick and wander."),
                   _f("viscosity", "Viscosity", 2.5e-4, 5e-5, 6e-4, "Physics", _H["visc"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("flame", p, pr, t)},
    "Mushroom Clouds": {
        "params": [_f("atwood", "Atwood number", 0.7, 0.2, 1.0, "Physics",
                      "A = (ρ_heavy − ρ_light)/(ρ_heavy + ρ_light), the density contrast across "
                      "the interface. It sets how hard the heavy fluid falls: higher A → faster, "
                      "narrower spikes and more vigorous mushroom roll-up."),
                   _f("gravity", "Gravity (sim units)", 1.2e-3, 4e-4, 3e-3, "Physics", _H["grav"]),
                   _f("viscosity", "Viscosity (sim units)", 1.5e-4, 3e-5, 5e-4, "Physics", _H["visc"]),
                   _f("perturbation", "Interface ripple (×)", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the initial interface ripple that seeds the fingers."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rt", p, pr, t)},
    "Rayleigh-Benard": {
        "params": [_f("buoyancy", "Buoyancy (Rayleigh)", 6e-3, 2e-3, 1.2e-2, "Physics",
                      "How hard the temperature difference pushes the fluid — effectively the "
                      "Rayleigh number. Higher → convection sets in faster and rolls break into "
                      "more vigorous, plume-like turbulence."),
                   _f("viscosity", "Viscosity (sim units)", 6e-4, 2e-4, 1.5e-3, "Physics",
                      "Damps the motion. Lower viscosity → a higher Rayleigh number → tighter, "
                      "more chaotic convection cells."),
                   _f("perturbation", "Seed ripple (×)", 1.0, 0.2, 3.0, "Physics",
                      "Amplitude of the tiny temperature perturbation that breaks the symmetry "
                      "and selects the cell wavelength."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("rb", p, pr, t)},
    "Chimney Plume": {
        "params": [_f("buoyancy", "Buoyancy", 5e-3, 2e-3, 1e-2, "Physics", _H["buoy"]),
                   _f("wind", "Crosswind speed", 0.30, 0.0, 0.55, "Physics",
                      "Speed of the horizontal wind blowing across the stack. Stronger wind bends "
                      "the plume over closer to the ground (a smaller plume rise). Below the plume's "
                      "own buoyant velocity the plume rises near-vertically; above it, the wind wins "
                      "and the plume lies over and streams downwind."),
                   _f("confinement", "Vorticity confinement", 6, 0, 20, "Physics", _H["conf"]),
                   _f("source", "Stack width (×)", 0.6, 0.3, 3.0, "Geometry",
                      "Width of the chimney source at the floor."),
                   _f("viscosity", "Viscosity", 8e-5, 0, 5e-4, "Physics", _H["visc"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_ns("wind", p, pr, t)},
    "Detonation": {
        "params": [{"name": "scene", "label": "Scene", "type": "choice", "group": "Geometry",
                    "choices": ["Open air", "Shock hits a city"], "default": "Open air",
                    "help": "Open air: a free blast wave expanding into still gas. Shock hits a "
                    "city: a ground burst whose blast diffracts around and reflects off two solid "
                    "towers — watch the Mach stems and shadow zones behind the buildings."},
                   _f("pressure", "Blast pressure (× ambient)", 10.0, 2.0, 40.0, "Physics",
                      "Pressure inside the charge, in units of ambient pressure (≈0.1 code). "
                      "Higher → a stronger, faster shock."),
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
                   _when(_f("dropsize", "Drop diameter (m)", 0.4, 0.2, 0.8, "Geometry",
                            "Diameter of the falling water blob (a parcel of water, not a "
                            "capillary droplet — there's no surface tension at this scale)."),
                         "scene", ["Drop & splash"]),
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
                   _when(_f("pourv", "Pour speed (m/s)", 1.4, 0.4, 3.0, "Physics",
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
        "params": [{"name": "init", "label": "Initial field", "type": "choice", "group": "Geometry",
                    "choices": ["Shear layers", "Random turbulence"], "default": "Shear layers",
                    "help": "Shear layers roll into Kelvin–Helmholtz billows; random turbulence "
                    "decays as vortices merge (the 2-D inverse cascade)."},
                   _f("viscosity", "Viscosity", 8e-5, 1e-5, 4e-4, "Physics", _H["visc"]),
                   _when(_f("perturbation", "Shear perturbation", 0.05, 0.005, 0.2, "Physics",
                            "Strength of the initial shear-layer kick that seeds the billows."),
                         "init", ["Shear layers"]),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_spectral(p, pr, t)},
    "Porous Flow": {
        "params": [_f("porosity", "Porosity  φ (void frac.)", 0.60, 0.40, 0.85, "Geometry",
                      "Fraction of the sample that is open pore space. Lower porosity (denser "
                      "grain packing) → far lower permeability."),
                   _f("grain", "Grain size (frac.)", 0.035, 0.02, 0.07, "Geometry",
                      "Radius of the packed grains as a fraction of the sample height."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_porous(p, pr, t)},
    "Turing Patterns": {
        "params": [{"name": "pattern", "label": "Pattern", "type": "choice", "group": "Geometry",
                    "choices": ["Spots", "Stripes", "Maze", "Mitosis", "Coral", "Waves"],
                    "default": "Spots",
                    "help": "Each pattern is a different (feed, kill) regime of the Gray–Scott "
                    "model — Pearson's classification of reaction–diffusion morphologies."},
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_reaction(p, pr, t)},
    "Ink in Motion": {
        "params": [_f("bands", "Dye bands", 6, 2, 14, "Geometry",
                      "How many stripes of dye to start with before the turbulence stirs them."),
                   _f("diffusion", "Dye diffusion", 1e-4, 0.0, 1e-3, "Physics",
                      "Molecular diffusion of the dye — higher blurs the fine filaments sooner."),
                   P_RES(), P_DUR()],
        "solve": lambda p, pr, t: _solve_mixing(p, pr, t)},
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
    "Candle Flame": {"method": "Low-Mach laminar diffusion flame · Navier–Stokes + mixture fraction",
        "blurb": "A real candle is a non-premixed (diffusion) flame: fuel vapour rises from the "
                 "wick, air is drawn in from the sides, and the two can only burn where they meet "
                 "in the right proportion. Modelled with fast chemistry, that burning sheet sits on "
                 "the stoichiometric surface; the heat it releases makes the gas buoyant, which "
                 "pulls in fresh air and lifts the products — giving the slender teardrop and the "
                 "characteristic tip flicker. Unlike the smoke plume, the flame here is the result "
                 "of combustion, not a recoloured buoyant jet.",
        "eq": r"$\partial_t Z+\mathbf{u}\!\cdot\!\nabla Z=\mathcal{D}\nabla^2 Z,\quad T(Z)=T_{\rm ad}\,\min\!\left(\dfrac{Z}{Z_{st}},\ \dfrac{1-Z}{1-Z_{st}}\right),\quad \mathbf{f}_b=\beta\,T(Z)\,\hat{\mathbf{y}}$",
        "numerics": "The incompressible projection solver carries a conserved mixture fraction Z "
                    "(Z = 1 in the fuel leaving the wick, Z = 0 in the surrounding air). In the "
                    "Burke–Schumann fast-chemistry limit the flame sheet sits exactly on Z = Z_st, "
                    "where the temperature peaks; T(Z) is a tent function of Z, and that heat drives "
                    "the Boussinesq buoyancy. The luminous field rendered is T(Z) — the reacting, "
                    "glowing zone.",
        "validation": "The flame anchors on the wick and self-organises into a steady teardrop with "
                       "a buoyancy-driven tip flicker — the hallmark of a laminar diffusion flame — "
                       "without any artificial forcing; the flicker frequency is reported in the plots."},
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
    "Rayleigh-Benard": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "Heat a shallow layer of fluid from below and cool it from above and, once the "
                 "temperature difference is large enough, pure conduction can no longer carry the "
                 "heat: the layer overturns. Warm fluid rises in plumes, cool fluid sinks, and the "
                 "motion organises into a regular train of counter-rotating convection cells — "
                 "Rayleigh–Bénard convection. It is the textbook example of pattern formation from "
                 "instability, and the same engine of buoyant overturning drives the atmosphere, "
                 "the oceans, boiling pots and the Earth's mantle.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\alpha g\,T\,\hat{\mathbf{y}},\quad \partial_t T+\mathbf{u}\!\cdot\!\nabla T=\kappa\nabla^2T,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The incompressible projection solver coupled to a transported temperature "
                    "field under the Boussinesq approximation (buoyancy ∝ T). The bottom and top "
                    "rows are held at fixed hot and cold temperatures (Dirichlet plates), the side "
                    "walls are insulating, and a tiny initial perturbation seeds the cells. The "
                    "ratio of buoyant forcing to viscous and diffusive damping is the Rayleigh number.",
        "validation": "Below a critical Rayleigh number the layer stays still (pure conduction); "
                       "above it, steady counter-rotating rolls appear and, at higher Ra, break into "
                       "unsteady plumes — the classic convection-onset behaviour."},
    "Chimney Plume": {"method": "Incompressible Navier–Stokes · projection",
        "blurb": "A buoyant plume leaves a stack into a steady crosswind. Near the source buoyancy "
                 "lifts it almost vertically, but the horizontal wind keeps pushing, so the plume "
                 "bends over into the familiar slanted chimney trail before levelling off downwind. "
                 "The balance between buoyancy and wind sets the 'plume rise' — the same physics "
                 "engineers use to size smokestacks and predict how pollutants disperse.",
        "eq": r"$\partial_t\mathbf{u}+(\mathbf{u}\!\cdot\!\nabla)\mathbf{u}=-\nabla p+\nu\nabla^2\mathbf{u}+\mathbf{f}_b,\quad \nabla\!\cdot\!\mathbf{u}=0$",
        "numerics": "The projection solver with a hot, dyed source at the floor and a velocity "
                    "inlet on the left that drives a uniform crosswind (zero-gradient outflow on the "
                    "right, open top). Boussinesq buoyancy lifts the dyed fluid while the mean wind "
                    "advects it downstream, so the steady plume trajectory emerges from the force balance.",
        "validation": "The plume rises then bends over, and its rise height falls as the crosswind "
                       "strengthens — the expected buoyancy-versus-momentum trade-off of plume-rise theory."},
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
                    "is a rigid body that rides on the fluid through a contact (penalty) "
                    "force, heaving and rolling as the water surface moves beneath it.",
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
        "validation": "With viscosity switched off the scheme conserves kinetic energy essentially "
                       "to round-off (relative drift below 10⁻⁸ over hundreds of steps) — the "
                       "hallmark of spectral accuracy.",
        "demo": "results/turbulence.gif"},
    "Turing Patterns": {"method": "Reaction–Diffusion · Gray–Scott",
        "blurb": "Two chemicals diffuse at different rates while one feeds on the other. From a "
                 "nearly uniform start, that simple competition spontaneously organises into "
                 "spots, stripes, mazes and self-replicating blobs — the mechanism Alan Turing "
                 "proposed in 1952 for how a featureless embryo becomes a patterned animal. A "
                 "small change in the feed/kill rates switches the whole morphology.",
        "eq": r"$\partial_t U = D_u\nabla^2U - UV^2 + F(1-U),\ \ \partial_t V = D_v\nabla^2V + UV^2 - (F{+}k)V$",
        "numerics": "Explicit time stepping of the two coupled reaction–diffusion equations on a "
                    "periodic grid, with a 9-point isotropic Laplacian for the diffusion term. "
                    "The (F, k) pair is taken from Pearson's classification to select each regime.",
        "validation": "Reproduces Pearson's catalogue of Gray–Scott regimes — the same (F, k) "
                       "values yield the published spot / stripe / maze / mitosis morphologies; "
                       "the concentrations stay bounded in [0, 1] throughout.",
        "demo": "results/gallery/rd_spots.gif"},
    "Quantum Ripples": {"method": "Schrödinger · split-step Fourier",
        "blurb": "A quantum particle isn't a dot but a wave of probability. Launch a wavepacket "
                 "and watch it spread, tunnel through a wall it classically could not cross, "
                 "interfere with itself through a double slit, or slosh coherently in a trap. "
                 "The glow is |ψ|² — where the particle is likely to be found.",
        "eq": r"$i\hbar\,\partial_t\psi = -\tfrac{\hbar^2}{2m}\nabla^2\psi + V(\mathbf{x})\,\psi$",
        "numerics": "The time-dependent Schrödinger equation by the split-step Fourier method: "
                    "a half-step potential phase kick, a full kinetic step applied as a diagonal "
                    "multiply in Fourier space (FFT), then another half potential kick. The split "
                    "is second-order accurate and exactly unitary; a soft absorbing border lets "
                    "scattered waves leave without reflecting.",
        "validation": "Because every step is unitary the total probability ∫|ψ|² is conserved to "
                       "round-off (≈ 10⁻¹⁴ drift in the closed harmonic well) — shown live in the "
                       "run info.",
        "demo": "results/gallery/qm_barrier.gif"},
    "Ink in Motion": {"method": "Chaotic mixing · spectral + passive scalar",
        "blurb": "Drop bands of dye into a turbulent flow and watch them stretch and fold into "
                 "ever-finer filaments — the route by which stirring mixes things long before "
                 "molecular diffusion could. The same chaotic advection mixes cream into coffee, "
                 "pollutants into the ocean, and plankton blooms across the sea surface.",
        "eq": r"$\partial_t c + (\mathbf{u}\!\cdot\!\nabla)c = \kappa\nabla^2 c$",
        "numerics": "The turbulent velocity comes from the same spectral vorticity solver; the "
                    "dye is a passive scalar advected by it with periodic bilinear semi-Lagrangian "
                    "transport (unconditionally stable) and a touch of spectral diffusion.",
        "validation": "Bilinear semi-Lagrangian advection is unconditionally stable and nearly "
                       "monotone — the dye stays within [0, 1] as the filaments thin (interpolation "
                       "is slightly diffusive, so a little contrast is lost rather than gained), the "
                       "signature of stirring-dominated mixing.",
        "demo": "results/gallery/mix_bands.gif"},
    "Porous Flow": {"method": "Pore-scale Lattice-Boltzmann · Darcy",
        "blurb": "Push fluid through a packed bed of grains and it threads a tortuous path "
                 "between them. Averaged over the sample, the flow rate is simply proportional to "
                 "the driving force — Darcy's law — and the constant of proportionality is the "
                 "permeability k, the single number that says how easily a rock, soil or filter "
                 "lets fluid through. Funoos resolves the pore-scale flow and measures k directly.",
        "eq": r"$\langle\mathbf{u}\rangle = -\tfrac{k}{\mu}\nabla p$",
        "numerics": "The same D2Q9 lattice-Boltzmann scheme, here in a periodic box driven by a "
                    "constant body force (Guo forcing) through a random grain pack, in the "
                    "viscous (Stokes) regime. Permeability is read off as k = ν⟨u⟩/g from the "
                    "volume-averaged pore velocity ⟨u⟩ — exactly how digital-rock physics "
                    "computes it.",
        "validation": "The measured permeability tracks the Kozeny–Carman relation "
                       "k ≈ φ³d²/180(1−φ)² across porosities, and rises monotonically with the "
                       "void fraction φ — the expected pore-scale behaviour (see the Plots).",
        "demo": "results/gallery/porous_phi60.gif"},
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
