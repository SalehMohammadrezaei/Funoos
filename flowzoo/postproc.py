"""Post-processing diagnostics for the player.

Each exhibit gets a few quantitative plots computed directly from the solved
frames (no extra solver runs): the periodic lift/Strouhal signal for the wind
tunnel, kinetic-energy & enstrophy histories for the turbulence and shock-bubble
cases, the blast-front radius, the dam-break surge front, the rising-plume
height, and so on. `plots(result)` returns a list of (title, rgb-ndarray)
images, themed to match the Studio so they sit naturally beside the animation.
"""
from __future__ import annotations

import numpy as np

# ---- theme (Funoos: deep-navy viewport, blue + lime accents) ----
_BG = "#0C1A2E"; _FG = "#C7D4E8"; _GRID = "#1c2c44"; _MUTED = "#7e8eaa"
_CYAN = "#6F90E8"; _AMBER = "#E1FC66"; _GOOD = "#9BE25A"


def _new_ax(xl, yl, title):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(6.2, 3.5), dpi=110)
    ax = fig.add_axes([0.135, 0.17, 0.83, 0.74])
    fig.patch.set_facecolor(_BG); ax.set_facecolor(_BG)
    for s in ax.spines.values():
        s.set_color(_GRID)
    ax.tick_params(colors=_MUTED, labelsize=8)
    ax.grid(True, color=_GRID, lw=0.6, alpha=0.7)
    ax.set_xlabel(xl, color=_FG, fontsize=9)
    ax.set_ylabel(yl, color=_FG, fontsize=9)
    ax.set_title(title, color=_FG, fontsize=11, fontweight="bold", loc="left", pad=8)
    return fig, ax, plt


def _rgb(fig, plt):
    fig.canvas.draw()
    w, h = fig.canvas.get_width_height()
    a = np.frombuffer(fig.canvas.buffer_rgba(), np.uint8).reshape(h, w, 4)[..., :3].copy()
    plt.close(fig)
    return a


def _vel(result):
    """List of (ux, uy) frames, or None."""
    if result.kind in ("lbm", "spectral"):
        return result.raw
    return result.hints.get("vel")


def _curl(ux, uy):
    dvdx = np.gradient(uy, axis=1); dudy = np.gradient(ux, axis=0)
    return dvdx - dudy


# ─────────────────────────  per-kind diagnostics  ─────────────────────────
def _ke_enstrophy(result, title):
    vel = _vel(result)
    if not vel:
        return []
    ke = [0.5 * float(np.mean(ux * ux + uy * uy)) for ux, uy in vel]
    ens = [0.5 * float(np.mean(_curl(ux, uy) ** 2)) for ux, uy in vel]
    t = np.linspace(0, 1, len(ke))
    out = []
    fig, ax, plt = _new_ax("time (normalised)", "energy / enstrophy (normalised)", title)
    ke = np.array(ke) / (max(ke) + 1e-30); ens = np.array(ens) / (max(ens) + 1e-30)
    ax.plot(t, ke, color=_CYAN, lw=2.2, label="kinetic energy")
    ax.plot(t, ens, color=_AMBER, lw=2.2, label="enstrophy")
    ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="best")
    ax.set_ylim(0, 1.05)
    out.append((title, _rgb(fig, plt)))
    return out


def _wind_tunnel(result):
    vel = result.raw
    if not vel:
        return []
    ny, nx = vel[0][0].shape
    h = result.hints
    ix = int(min(nx - 2, h.get("probe_x", int(0.62 * nx))))
    jy = int(h.get("probe_y", ny // 2))
    sig = np.array([uy[jy, ix] for _ux, uy in vel])          # transverse velocity ~ lift
    sig = sig - sig.mean()
    t = np.arange(len(sig))
    out = []
    # 1) the periodic lift signal
    fig, ax, plt = _new_ax("frame", "transverse velocity  v  (lift proxy)",
                           "Vortex shedding — periodic side-force")
    ax.plot(t, sig, color=_CYAN, lw=1.8)
    ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5)
    out.append(("Lift signal", _rgb(fig, plt)))
    # 2) spectrum → Strouhal number
    n = len(sig)
    if n >= 16:
        win = np.hanning(n); sp = np.abs(np.fft.rfft(sig * win))
        fr = np.fft.rfftfreq(n, d=1.0)                       # cycles per frame
        k = int(np.argmax(sp[1:]) + 1) if len(sp) > 2 else 0
        fpk = fr[k] if k else 0.0
        fig, ax, plt = _new_ax("frequency  (cycles / frame)", "amplitude",
                               "Shedding spectrum")
        ax.plot(fr, sp, color=_AMBER, lw=1.8)
        label = ""
        D, U, fdt = h.get("D"), h.get("U"), h.get("frame_dt_steps")
        if k and D and U and fdt:
            st = (fpk / fdt) * D / U
            ax.axvline(fpk, color=_CYAN, lw=1.4, ls="--")
            label = f"St = f·D/U ≈ {st:.2f}   (expected ≈ 0.2)"
            ax.text(0.97, 0.92, label, transform=ax.transAxes, color=_GOOD, fontsize=9,
                    ha="right", va="top", fontweight="bold")
        out.append(("Strouhal spectrum", _rgb(fig, plt)))
    return out


def _plume_height(result):
    raw = result.raw
    if not raw:
        return []
    ny = raw[0].shape[0]
    smoke = result.hints.get("label", "").startswith("smoke")
    out = []
    if smoke:
        hgt = []
        for s in raw:
            col = s.max(axis=1)
            rows = np.where(col > 0.15)[0]
            hgt.append((rows.max() if len(rows) else 0) / ny)
        t = np.linspace(0, 1, len(hgt))
        fig, ax, plt = _new_ax("time (normalised)", "plume top  (fraction of height)",
                               "Buoyant plume rise")
        ax.plot(t, hgt, color=_CYAN, lw=2.2)
        ax.set_ylim(0, 1.02)
        out.append(("Plume rise", _rgb(fig, plt)))
    else:                                                    # Rayleigh–Taylor mixing width
        wid = []
        for s in raw:
            prof = s.mean(axis=1)
            mix = np.where((prof > 0.1) & (prof < 0.9))[0]
            wid.append((mix.max() - mix.min() if len(mix) else 0) / ny)
        t = np.linspace(0, 1, len(wid))
        fig, ax, plt = _new_ax("time (normalised)", "mixing-layer width  (fraction)",
                               "Rayleigh–Taylor mixing growth")
        ax.plot(t, wid, color=_AMBER, lw=2.2)
        out.append(("Mixing width", _rgb(fig, plt)))
    out += _ke_enstrophy(result, "Kinetic energy & enstrophy")
    return out


def _blast(result):
    raw = result.raw
    if not raw:
        return []
    ny, nx = raw[0].shape
    h = result.hints
    cx = nx * (0.20 if h.get("building") else 0.5)
    cy = ny * (0.14 if h.get("building") else 0.5)
    yy, xx = np.mgrid[0:ny, 0:nx]
    rr = np.hypot(xx - cx, yy - cy)
    R = []
    for rho in raw:
        gy, gx = np.gradient(rho); sch = np.hypot(gx, gy)
        R.append(rr.flat[int(np.argmax(sch))])              # radius of the strongest gradient (shock)
    R = np.array(R) / (np.hypot(nx, ny))
    t = np.linspace(0, 1, len(R))
    fig, ax, plt = _new_ax("time (normalised)", "shock-front radius  (fraction)",
                           "Blast wave expansion")
    ax.plot(t, R, color=_CYAN, lw=2.2)
    return [("Shock radius", _rgb(fig, plt))]


def _bubble(result):
    return _ke_enstrophy(result, "Baroclinic vorticity growth (KE & enstrophy)")


def _particles(result):
    raw = result.raw
    if not raw:
        return []
    h = result.hints
    ke = [0.5 * float(np.mean(d[:, 2] ** 2)) for d in raw]
    ke = np.array(ke) / (max(ke) + 1e-30)
    t = np.linspace(0, 1, len(ke))
    out = []
    fig, ax, plt = _new_ax("time (normalised)", "kinetic energy (normalised)",
                           "Kinetic energy of the water")
    ax.plot(t, ke, color=_CYAN, lw=2.2)
    out.append(("Kinetic energy", _rgb(fig, plt)))
    # surge front (water spreading along the floor)
    Ly = h.get("Ly", 1.0)
    front = []
    for d in raw:
        low = d[d[:, 1] < 0.12 * Ly]
        front.append(low[:, 0].max() if len(low) else 0.0)
    front = np.array(front) / (h.get("Lx", 1.0))
    fig, ax, plt = _new_ax("time (normalised)", "front position  (fraction of tank)",
                           "Leading surge front")
    ax.plot(t, front, color=_AMBER, lw=2.2)
    out.append(("Surge front", _rgb(fig, plt)))
    return out


def _porous(result):
    h = result.hints
    phi = h.get("porosity", 0.6); k = h.get("permeability", 0.0); d = 2.0 * h.get("grain", 12)
    P = np.linspace(0.35, 0.9, 120)
    kc = P ** 3 * d * d / (180.0 * (1.0 - P) ** 2)        # Kozeny–Carman reference
    fig, ax, plt = _new_ax("porosity  φ", "permeability  k  (lattice cells²)",
                           "Permeability vs porosity")
    ax.plot(P, kc, color=_MUTED, lw=1.8, ls="--", label="Kozeny–Carman")
    ax.scatter([phi], [max(k, 1e-9)], color=_AMBER, s=90, zorder=5, edgecolor="#1a1a1a",
               label=f"measured: φ={phi:.2f}, k={k:.2f}")
    ax.set_yscale("log")
    ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="upper left")
    return [("Permeability (Darcy)", _rgb(fig, plt))]


def plots(result):
    """Return [(title, rgb ndarray), …] of diagnostics for this result."""
    try:
        k = result.kind
        if k == "lbm":
            return _porous(result) if result.hints.get("permeability") is not None else _wind_tunnel(result)
        if k == "spectral":
            return _ke_enstrophy(result, "2-D turbulence — energy & enstrophy")
        if k == "ns":
            return _plume_height(result)
        if k == "density":
            return _blast(result) if result.hints.get("mode") == "blast" else _bubble(result)
        if k == "particles":
            return _particles(result)
    except Exception:
        pass
    return []
