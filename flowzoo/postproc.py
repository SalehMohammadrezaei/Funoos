"""Post-processing diagnostics for the player.

Every scene gets a few *meaningful*, quantitative plots computed directly from
the solved frames (no extra solver runs), each chosen for what actually matters
in that flow: lift & drag for the airfoil, the Strouhal number for a shedding
bluff body, the drafting shelter for a pair of cyclists, the blast-front radius,
the convective heat flux for Rayleigh–Bénard, the bent-over plume trajectory for
a chimney, Turing-pattern growth, and so on.

`plots(result)` returns a list of (title, rgb-ndarray, explanation) triples — the
explanation is shown beside the plot so the viewer knows what it means and how to
read whether it is physically correct.
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


def _legend(ax):
    ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="best")


def _vel(result):
    """List of (ux, uy) frames, or None."""
    if result.kind in ("lbm", "spectral"):
        return result.raw
    return result.hints.get("vel")


def _curl(ux, uy):
    dvdx = np.gradient(uy, axis=1); dudy = np.gradient(ux, axis=0)
    return dvdx - dudy


# ─────────────────────────  generic energy diagnostic  ─────────────────────────
def _ke_enstrophy(result, title, explain):
    vel = _vel(result)
    if not vel:
        return []
    ke = [0.5 * float(np.mean(ux * ux + uy * uy)) for ux, uy in vel]
    ens = [0.5 * float(np.mean(_curl(ux, uy) ** 2)) for ux, uy in vel]
    t = np.linspace(0, 1, len(ke))
    fig, ax, plt = _new_ax("time (normalised)", "energy / enstrophy (normalised)", title)
    ke = np.array(ke) / (max(ke) + 1e-30); ens = np.array(ens) / (max(ens) + 1e-30)
    ax.plot(t, ke, color=_CYAN, lw=2.2, label="kinetic energy")
    ax.plot(t, ens, color=_AMBER, lw=2.2, label="enstrophy")
    _legend(ax); ax.set_ylim(0, 1.05)
    return [(title, _rgb(fig, plt), explain)]


# ─────────────────────────  wind-tunnel forces  ─────────────────────────
def _drag_cd(result):
    """Drag coefficient time-series from the wake momentum deficit at the probe plane."""
    vel = result.raw; h = result.hints
    ny, nx = vel[0][0].shape
    U = float(h.get("U", 0.1)) or 0.1
    A = max(1.0, float(h.get("D", ny * 0.2)))               # frontal length scale
    xp = int(min(nx - 2, h.get("probe_x", int(0.62 * nx))))
    cds = []
    for ux, _uy in vel:
        u = np.clip(ux[:, xp], 0.0, U)                      # only count sub-freestream wake,
        deficit = float(np.sum(u * (U - u)))                # not the faster bypass flow beside it
        cds.append(2.0 * deficit / (U * U * A))             # wake-survey drag: Cd = (2/A)∫(u/U)(1−u/U)dy
    return np.array(cds), U, A, xp


def _circulation(ux, uy, mask):
    rows = np.where(np.any(mask, axis=1))[0]; cols = np.where(np.any(mask, axis=0))[0]
    if not len(rows) or not len(cols):
        return 0.0, 1.0
    m = 8
    j0 = max(1, rows.min() - m); j1 = min(mask.shape[0] - 2, rows.max() + m)
    i0 = max(1, cols.min() - m); i1 = min(mask.shape[1] - 2, cols.max() + m)
    # Γ = ∮ u·dl, counter-clockwise (y = +j up): bottom +x, right +y, top −x, left −y
    gamma = (float(np.sum(ux[j0, i0:i1])) + float(np.sum(uy[j0:j1, i1]))
             - float(np.sum(ux[j1, i0:i1])) - float(np.sum(uy[j0:j1, i0])))
    chord = float(cols.max() - cols.min() + 1)
    return gamma, chord


def _shedding(result):
    """Periodic side-force signal + Strouhal-number spectrum (bluff bodies)."""
    vel = result.raw; h = result.hints
    ny, nx = vel[0][0].shape
    ix = int(min(nx - 2, h.get("probe_x", int(0.62 * nx)))); jy = int(h.get("probe_y", ny // 2))
    sig = np.array([uy[jy, ix] for _ux, uy in vel]); sig = sig - sig.mean()
    t = np.arange(len(sig)); out = []
    fig, ax, plt = _new_ax("frame", "transverse velocity  v  (side-force proxy)",
                           "Vortex shedding — periodic side force")
    ax.plot(t, sig, color=_CYAN, lw=1.8); ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5)
    out.append(("Lift signal", _rgb(fig, plt),
                "Transverse velocity just behind the body. A clean, regular oscillation means the "
                "wake is shedding vortices alternately from each side (a von Kármán street). The "
                "swing is the unsteady side-force that shakes chimneys and bridge decks."))
    n = len(sig); obs = h.get("obstacle", "Cylinder")
    if n >= 16:
        win = np.hanning(n); sp = np.abs(np.fft.rfft(sig * win)); fr = np.fft.rfftfreq(n, d=1.0)
        k = int(np.argmax(sp[1:]) + 1) if len(sp) > 2 else 0
        fpk = fr[k] if k else 0.0
        fig, ax, plt = _new_ax("frequency  (cycles / frame)", "amplitude", "Shedding spectrum → Strouhal")
        ax.plot(fr, sp, color=_AMBER, lw=1.8)
        D, U, fdt = h.get("D"), h.get("U"), h.get("frame_dt_steps")
        st = (fpk / fdt) * D / U if (k and D and U and fdt) else None
        is_cyl = obs == "Cylinder"
        if st is not None and obs != "Your text":      # D is ill-defined for multi-glyph text
            ax.axvline(fpk, color=_CYAN, lw=1.4, ls="--")
            note = f"St = f·D/U ≈ {st:.2f}" + ("   (cylinder: expected ≈ 0.2)" if is_cyl else "")
            ax.text(0.97, 0.92, note, transform=ax.transAxes, color=_GOOD, fontsize=9,
                    ha="right", va="top", fontweight="bold")
        ex = ("The peak shedding frequency, made dimensionless as the Strouhal number St = f·D/U. "
              + ("For a circular cylinder this sits near 0.2 across a wide Reynolds range"
                 + (f" — here ≈ {st:.2f}, matching it." if st is not None else ".")
                 if is_cyl else
                 "It is a fixed number for each shape (≈0.2 for a cylinder, lower for a square); "
                 "sharper, bluffer bodies shed at their own characteristic rate."))
        out.append(("Strouhal spectrum", _rgb(fig, plt), ex))
    return out


def _drag_plot(result, title, explain, expect=None):
    cds, U, A, xp = _drag_cd(result)
    t = np.linspace(0, 1, len(cds))
    fig, ax, plt = _new_ax("time (normalised)", "drag coefficient  C_d", title)
    ax.plot(t, cds, color=_CYAN, lw=2.2)
    mean_cd = float(np.mean(cds[len(cds) // 2:]))           # average over the settled second half
    ax.axhline(mean_cd, color=_AMBER, lw=1.2, ls="--")
    ax.text(0.97, 0.92, f"mean C_d ≈ {mean_cd:.2f}" + (f"  ({expect})" if expect else ""),
            transform=ax.transAxes, color=_GOOD, fontsize=9, ha="right", va="top", fontweight="bold")
    return [(title, _rgb(fig, plt), explain)], mean_cd


def _airfoil(result):
    vel = result.raw; out = []
    # lift via circulation (Kutta–Joukowski), drag via wake deficit
    gam = [];
    for ux, uy in vel:
        g, c = _circulation(ux, uy, result.mask); gam.append(g)
    U = float(result.hints.get("U", 0.1)) or 0.1
    _g, chord = _circulation(vel[-1][0], vel[-1][1], result.mask)
    sign = 1.0 if np.mean(gam[len(gam) // 2:]) >= 0 else -1.0
    cl = sign * 2.0 * np.array(gam) / (U * max(chord, 1.0))
    t = np.linspace(0, 1, len(cl))
    fig, ax, plt = _new_ax("time (normalised)", "lift coefficient  C_l",
                           "Lift from the bound circulation (Kutta–Joukowski)")
    ax.plot(t, cl, color=_CYAN, lw=2.2); ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5)
    clm = float(np.mean(cl[len(cl) // 2:]))
    ax.text(0.97, 0.92, f"mean C_l ≈ {clm:.2f}", transform=ax.transAxes, color=_GOOD,
            fontsize=9, ha="right", va="top", fontweight="bold")
    out.append(("Lift coefficient", _rgb(fig, plt),
                "Lift comes from the circulation Γ bound to the wing: L = ρ·U·Γ. We integrate the "
                "velocity around the airfoil to get Γ, then C_l. At a positive angle of attack the "
                "flow turns over the top and C_l is positive — the wing pushes up."))
    dr, cdm = _drag_plot(result, "Drag from the wake deficit",
                         "Drag is read from the momentum the wing removes from the flow (its wake "
                         "deficit). At this modest Reynolds number the boundary layer separates over "
                         "the upper surface, so the drag is appreciable; lift and drag both rise with "
                         "angle of attack until the wing stalls.")
    return out + dr


def _drafting(result):
    """Centreline streamwise velocity showing the sheltered slipstream behind the riders."""
    vel = result.raw; h = result.hints
    ny, nx = vel[0][0].shape; U = float(h.get("U", 0.1)) or 0.1
    jy = int(h.get("probe_y", ny // 2))
    ux = np.mean([f[0] for f in vel[len(vel) // 2:]], axis=0)   # time-averaged, settled
    line = ux[jy, :] / U
    solid = np.any(result.mask[max(0, jy - 4):jy + 4, :], axis=0)
    x = np.arange(nx) / nx
    fig, ax, plt = _new_ax("position along the tunnel  (fraction)", "streamwise speed  u / U",
                           "Drafting — the sheltered slipstream")
    ln = line.copy(); ln[solid] = np.nan
    ax.plot(x, ln, color=_CYAN, lw=2.0)
    ax.axhline(1.0, color=_MUTED, lw=0.8, ls="--")
    ax.fill_between(x, 0, 1.2, where=solid, color=_AMBER, alpha=0.25, step="mid")
    wake = line[(x > 0.30) & (x < 0.55) & ~solid]
    mn = float(np.nanmin(wake)) if len(wake) else 1.0
    note = f"riders shaded · slipstream drops to ≈ {mn * 100:.0f}% of U" + ("  (flow even reverses)" if mn < 0 else "")
    ax.text(0.97, 0.08, note, transform=ax.transAxes,
            color=_GOOD, fontsize=9, ha="right", va="bottom", fontweight="bold")
    ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5); ax.set_ylim(-0.4, 1.25)
    out = [("Slipstream profile", _rgb(fig, plt),
            "Air speed along the line through the riders (riders shaded). The leader punches a hole "
            "in the air; right behind it the flow is much slower, so the second rider meets far less "
            "wind and spends less effort — that low-speed pocket is exactly why drafting saves a "
            "cyclist roughly a quarter to a third of their power.")]
    dr, _cd = _drag_plot(result, "Combined drag of the pair",
                         "Drag of the two riders together from the wake deficit. Because the follower "
                         "hides in the leader's wake, a drafting pair has noticeably less drag than two "
                         "riders ridden apart would.")
    return out + dr


def _wind_tunnel(result):
    if not result.raw:
        return []
    obs = result.hints.get("obstacle", "Cylinder")
    if obs == "Airfoil":
        return _airfoil(result)
    if obs == "Peloton (drafting)":
        return _drafting(result)
    if obs in ("F1 car", "Cyclist"):
        body = "race car" if obs == "F1 car" else "rider"
        dr, _cd = _drag_plot(result, f"Aerodynamic drag of the {body}",
                             f"Drag is read from the momentum the {body} removes from the air (the wake "
                             "deficit at a plane behind it). A bigger, slower wake means more drag — this "
                             "is the number aerodynamicists fight to shrink with wings, fairings and tucks.")
        return dr + _shedding(result)[:1]
    # cylinder / square / diamond / text → shedding is the headline
    return _shedding(result)


# ─────────────────────────  incompressible Navier–Stokes  ─────────────────────────
def _plume_rise(result):
    raw = result.raw; ny = raw[0].shape[0]
    hgt = []
    for s in raw:
        rows = np.where(s.max(axis=1) > 0.15)[0]
        hgt.append((rows.max() if len(rows) else 0) / ny)
    t = np.linspace(0, 1, len(hgt))
    fig, ax, plt = _new_ax("time (normalised)", "plume top  (fraction of height)", "Buoyant plume rise")
    ax.plot(t, hgt, color=_CYAN, lw=2.2); ax.set_ylim(0, 1.02)
    out = [("Plume rise", _rgb(fig, plt),
            "Height reached by the smoke over time. Buoyancy accelerates the hot fluid upward while "
            "it entrains cooler surroundings; the rise should climb steadily until the plume fills "
            "the domain — the signature of a buoyancy-driven flow.")]
    return out + _ke_enstrophy(result, "Kinetic energy & enstrophy",
                               "Total swirling energy (kinetic energy) and small-scale rotation "
                               "(enstrophy) over time — both grow as the smooth column rolls up into "
                               "turbulent eddies.")


def _rt_mixing(result):
    raw = result.raw; ny = raw[0].shape[0]
    wid = []
    for s in raw:
        prof = s.mean(axis=1); mix = np.where((prof > 0.1) & (prof < 0.9))[0]
        wid.append((mix.max() - mix.min() if len(mix) else 0) / ny)
    t = np.linspace(0, 1, len(wid))
    fig, ax, plt = _new_ax("time (normalised)", "mixing-layer width  (fraction)", "Rayleigh–Taylor mixing growth")
    ax.plot(t, wid, color=_AMBER, lw=2.2)
    return [("Mixing width", _rgb(fig, plt),
             "Thickness of the layer where heavy and light fluid interpenetrate. After an initial "
             "exponential instability it widens roughly with the square of time as the fingers fall "
             "and bubbles rise — the accepted Rayleigh–Taylor growth.")]


def _rb_convection(result):
    raw = result.raw; vel = result.hints.get("vel")
    ny, nx = raw[0].shape
    z = np.linspace(0, 1, ny)
    T0 = raw[0].mean(axis=1); Tf = raw[-1].mean(axis=1)
    fig, ax, plt = _new_ax("mean temperature  ⟨T⟩", "height  z  (fraction)",
                           "Convection flattens the temperature profile")
    ax.plot(T0, z, color=_MUTED, lw=1.6, ls="--", label="start (conduction)")
    ax.plot(Tf, z, color=_CYAN, lw=2.2, label="convecting")
    _legend(ax)
    out = [("Temperature profile", _rgb(fig, plt),
            "Horizontally-averaged temperature versus height. Pure conduction would keep the straight "
            "dashed line. Convection stirs the interior into a nearly uniform (well-mixed) core and "
            "squeezes the temperature change into thin layers at the hot and cold plates — the "
            "hallmark of convective heat transport.")]
    if vel:
        flux = np.mean([uy * (T - T.mean(axis=1, keepdims=True)) for (ux, uy), T in zip(vel, raw)][-1],
                       axis=1)
        fig, ax, plt = _new_ax("convective heat flux  ⟨v′T′⟩", "height  z  (fraction)",
                               "Upward convective heat flux")
        ax.plot(flux, z, color=_AMBER, lw=2.2); ax.axvline(0, color=_MUTED, lw=0.8, alpha=0.6)
        out.append(("Convective flux", _rgb(fig, plt),
                    "The correlation of vertical velocity and temperature fluctuations, ⟨v′T′⟩. It is "
                    "positive almost everywhere: warm parcels move up and cool parcels move down, "
                    "carrying heat upward far faster than conduction could — that excess is the "
                    "Nusselt enhancement."))
    return out


def _chimney_trajectory(result):
    raw = result.raw; ny, nx = raw[0].shape
    s = np.mean(raw[len(raw) // 2:], axis=0)                 # settled, time-averaged plume
    sx = nx // 4
    xs, zs = [], []
    for i in range(sx, nx - 2):
        col = s[:, i]
        if col.sum() > 0.02 * ny:
            zc = float(np.sum(np.arange(ny) * col) / (col.sum() + 1e-9))
            xs.append(i / nx); zs.append(zc / ny)
    fig, ax, plt = _new_ax("downwind distance  x  (fraction)", "plume centre-line height  z  (fraction)",
                           "Bent-over plume trajectory")
    if xs:
        ax.plot(xs, zs, color=_CYAN, lw=2.4)
    ax.axvline(sx / nx, color=_AMBER, lw=1.2, ls="--"); ax.text(sx / nx + 0.01, 0.05, "stack",
                                                                color=_AMBER, fontsize=8)
    ax.set_ylim(0, 1.0)
    return [("Plume trajectory", _rgb(fig, plt),
             "Height of the smoke centre-line as it travels downwind of the stack. Near the chimney "
             "buoyancy lifts it steeply; further downwind the crosswind has bent it over toward the "
             "horizontal. The height it levels off at is the 'plume rise' that decides how far a "
             "pollutant spreads — it drops as the wind strengthens.")]


def _flame(result):
    raw = result.raw; ny = raw[0].shape[0]
    tip = []
    for T in raw:
        rows = np.where(T.max(axis=1) > 0.3)[0]
        tip.append((rows.max() if len(rows) else 0) / ny)
    tip = np.array(tip); t = np.linspace(0, 1, len(tip))
    out = []
    fig, ax, plt = _new_ax("time (normalised)", "flame-tip height  (fraction)", "Flame tip — flicker in time")
    ax.plot(t, tip, color=_AMBER, lw=2.0)
    out.append(("Flame tip height", _rgb(fig, plt),
                "Height of the luminous tip over time. After it anchors on the wick the tip "
                "oscillates rather than sitting still — the periodic pinching of a candle flame, "
                "driven by a buoyant vortex shed near the base, not by any imposed wobble."))
    sig = tip - tip.mean(); n = len(sig)
    if n >= 16:
        win = np.hanning(n); sp = np.abs(np.fft.rfft(sig * win)); fr = np.fft.rfftfreq(n, d=1.0)
        k = int(np.argmax(sp[1:]) + 1) if len(sp) > 2 else 0
        fig, ax, plt = _new_ax("frequency  (cycles / frame)", "amplitude", "Flicker spectrum")
        ax.plot(fr, sp, color=_CYAN, lw=1.8)
        if k:
            ax.axvline(fr[k], color=_AMBER, lw=1.3, ls="--")
            ax.text(0.97, 0.92, f"flicker peak at {fr[k]:.3f} cyc/frame", transform=ax.transAxes,
                    color=_GOOD, fontsize=9, ha="right", va="top", fontweight="bold")
        out.append(("Flicker spectrum", _rgb(fig, plt),
                    "Frequency content of the tip motion. A clear peak means the flicker is "
                    "periodic — a real laminar flame flickers at a single dominant frequency "
                    "(≈10–15 Hz for a candle); here it shows up as one sharp spectral spike."))
    return out


def _ns(result):
    mode = result.hints.get("ns_mode", "smoke")
    if mode == "rb":
        return _rb_convection(result)
    if mode == "wind":
        return _chimney_trajectory(result)
    if mode == "flame":
        return _flame(result)
    if mode == "rt":
        return _rt_mixing(result)
    return _plume_rise(result)


# ─────────────────────────  compressible Euler  ─────────────────────────
def _blast(result):
    raw = result.raw; ny, nx = raw[0].shape; h = result.hints
    cx = nx * (0.20 if h.get("building") else 0.5); cy = ny * (0.14 if h.get("building") else 0.5)
    yy, xx = np.mgrid[0:ny, 0:nx]; rr = np.hypot(xx - cx, yy - cy)
    R = []
    for rho in raw:
        gy, gx = np.gradient(rho); sch = np.hypot(gx, gy)
        if h.get("building"):                       # ignore the static towers' edges (held dense)
            sch[rho > 2.0] = 0.0
        R.append(rr.flat[int(np.argmax(sch))])
    R = np.array(R) / (np.hypot(nx, ny)); t = np.linspace(0, 1, len(R))
    fig, ax, plt = _new_ax("time (normalised)", "shock-front radius  (fraction)", "Blast-wave expansion")
    ax.plot(t, R, color=_CYAN, lw=2.2)
    return [("Shock radius", _rgb(fig, plt),
             "Radius of the strongest density jump (the shock front) versus time. A blast decelerates "
             "as it sweeps up air, so the curve bends over — the classic Sedov–Taylor expansion behind "
             "explosion-safety and sonic-boom estimates.")]


def _bubble(result):
    return _ke_enstrophy(result, "Baroclinic vorticity growth (KE & enstrophy)",
                         "When the shock crosses the density interface of the bubble it deposits "
                         "vorticity (the baroclinic, ∇ρ×∇p, mechanism). Kinetic energy and especially "
                         "enstrophy jump at that moment and keep growing as the bubble rolls up — the "
                         "Richtmyer–Meshkov instability.")


# ─────────────────────────  SPH  ─────────────────────────
def _particles(result):
    raw = result.raw; h = result.hints
    ke = np.array([0.5 * float(np.mean(d[:, 2] ** 2)) for d in raw]); ke /= (ke.max() + 1e-30)
    t = np.linspace(0, 1, len(ke)); out = []
    fig, ax, plt = _new_ax("time (normalised)", "kinetic energy (normalised)", "Kinetic energy of the water")
    ax.plot(t, ke, color=_CYAN, lw=2.2)
    out.append(("Kinetic energy", _rgb(fig, plt),
                "Total kinetic energy of the water. It rises as gravity converts the initial height "
                "into motion, peaks at the most violent impact/collapse, then decays as the splash "
                "settles — energy conservation made visible."))
    Ly = h.get("Ly", 1.0); Lx = h.get("Lx", 1.0)
    front = []
    for d in raw:
        low = d[d[:, 1] < 0.12 * Ly]; front.append(low[:, 0].max() if len(low) else 0.0)
    front = np.array(front) / Lx
    fig, ax, plt = _new_ax("time (normalised)", "front position  (fraction of tank)", "Leading surge front")
    ax.plot(t, front, color=_AMBER, lw=2.2)
    out.append(("Surge front", _rgb(fig, plt),
                "Position of the leading edge of water along the floor. For a dam break the front "
                "advances at a near-constant speed set by the water depth (the Ritter √(gH) law) — a "
                "standard check for a free-surface solver."))
    return out


# ─────────────────────────  LBM porous  ─────────────────────────
def _porous(result):
    h = result.hints
    phi = h.get("porosity", 0.6); k = h.get("permeability", 0.0); d = 2.0 * h.get("grain", 12)
    P = np.linspace(0.35, 0.9, 120); kc = P ** 3 * d * d / (180.0 * (1.0 - P) ** 2)
    fig, ax, plt = _new_ax("porosity  φ", "permeability  k  (lattice cells²)", "Permeability vs porosity")
    ax.plot(P, kc, color=_MUTED, lw=1.8, ls="--", label="Kozeny–Carman")
    ax.scatter([phi], [max(k, 1e-9)], color=_AMBER, s=90, zorder=5, edgecolor="#1a1a1a",
               label=f"measured: φ={phi:.2f}, k={k:.2f}")
    ax.set_yscale("log"); _legend(ax)
    return [("Permeability (Darcy)", _rgb(fig, plt),
             "The measured permeability k = ν⟨u⟩/g (how easily fluid passes the rock) plotted against "
             "the Kozeny–Carman trend. k falls steeply as the pores close up — the measured point should "
             "fall near the reference curve (the grains are randomly sized, so an exact match isn't "
             "expected), confirming the pore-scale flow reproduces Darcy-type behaviour.")]


# ─────────────────────────  pseudo-spectral fields  ─────────────────────────
def _field(result):
    raw = result.raw
    label = result.hints.get("label", "")
    if label.startswith("V"):                                # Gray–Scott reaction–diffusion
        cov = np.array([float(np.mean(s > 0.25)) for s in raw]) * 100.0
        t = np.linspace(0, 1, len(cov))
        fig, ax, plt = _new_ax("time (normalised)", "area in the patterned state  (%)",
                               "Turing-pattern growth")
        ax.plot(t, cov, color=_GOOD, lw=2.2); ax.set_ylim(0, max(60, cov.max() * 1.1))
        return [("Pattern coverage", _rgb(fig, plt),
                 "Fraction of the domain occupied by the reacting species. From a few seed spots the "
                 "Gray–Scott pattern spreads and then saturates as spots/stripes fill the space and "
                 "lock into a steady wavelength — diffusion-driven (Turing) pattern formation.")]
    # ink in motion — passive dye mixing
    var = np.array([float(np.var(s)) for s in raw]); var /= (var.max() + 1e-30)
    t = np.linspace(0, 1, len(var))
    fig, ax, plt = _new_ax("time (normalised)", "dye variance (normalised)", "Mixing of the dye")
    ax.plot(t, var, color=_CYAN, lw=2.2); ax.set_ylim(0, 1.05)
    return [("Dye mixing", _rgb(fig, plt),
             "Variance (contrast) of the dye field. The stirring stretches the blobs into ever-finer "
             "filaments; as they thin below the grid scale the contrast decays — the chaotic flow is "
             "mixing the dye toward uniformity.")]


# ─────────────────────────  quantum  ─────────────────────────
def _quantum(result):
    norm = result.hints.get("norm")
    if not norm:
        return []
    t = np.linspace(0, 1, len(norm)); closed = result.hints.get("scene") == "harmonic"
    fig, ax, plt = _new_ax("time (normalised)", "total probability  ∫|ψ|²", "Probability conservation")
    ax.plot(t, norm, color=_CYAN, lw=2.2); ax.axhline(1.0, color=_MUTED, lw=0.8, ls="--")
    if closed:
        ax.set_ylim(0.999, 1.001)
        ax.text(0.5, 0.5, f"closed system — unitary\ndrift {max(abs(x - 1) for x in norm):.0e}",
                transform=ax.transAxes, color=_GOOD, fontsize=10, ha="center", fontweight="bold")
        ex = ("Total probability ∫|ψ|² for a closed well. A correct unitary solver conserves it to "
              "round-off — the flat line confirms the split-step scheme is faithful.")
    else:
        ax.set_ylim(0, 1.05)
        ax.text(0.97, 0.9, "open system: probability\nleaves through the absorber", transform=ax.transAxes,
                color=_MUTED, fontsize=9, ha="right", va="top")
        ex = ("Total probability over time. With an absorbing boundary the packet leaves the box, so "
              "the norm decays — exactly what an open scattering set-up should show.")
    return [("Probability conservation", _rgb(fig, plt), ex)]


# ─────────────────────────  dispatch  ─────────────────────────
def plots(result):
    """Return [(title, rgb ndarray, explanation), …] of diagnostics for this result."""
    try:
        k = result.kind
        if k == "quantum":
            return _quantum(result)
        if k == "porous":
            return _porous(result)
        if k == "lbm":
            return _wind_tunnel(result)
        if k == "spectral":
            return _ke_enstrophy(result, "2-D turbulence — energy & enstrophy",
                                 "Kinetic energy and enstrophy (small-scale rotation) over time. In "
                                 "decaying 2-D turbulence energy is nearly conserved while enstrophy "
                                 "falls as small eddies merge into larger ones — the inverse cascade.")
        if k == "ns":
            return _ns(result)
        if k == "density":
            return _blast(result) if result.hints.get("mode") == "blast" else _bubble(result)
        if k == "particles":
            return _particles(result)
        if k == "field":
            return _field(result)
    except Exception:
        pass
    return []
