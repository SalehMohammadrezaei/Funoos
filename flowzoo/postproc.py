"""Diagnostics: measurements first, plots second.

`metrics(result)`  -> {name: number}          scalar measurements (tested without images)
`series(result)`   -> {name: [values...]}      time series (first key is the time axis)
`plots(result)`    -> [(title, rgb, explain)]  figures built from the two above

Every plot's explanation states the definition, units, data source and sampling
interval, the assumptions, and what has (and has not) been checked. Absolute
values are plotted with their units; nothing is normalised by its own maximum.
"""
from __future__ import annotations

import numpy as np

# ---- theme (Funoos: deep-navy viewport, blue + lime accents) ----
_BG = "#0C1A2E"; _FG = "#C7D4E8"; _GRID = "#1c2c44"; _MUTED = "#7e8eaa"
_CYAN = "#6F90E8"; _AMBER = "#E1FC66"; _GOOD = "#9BE25A"; _WARN = "#f0a35a"


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


_SVG_SINK = None      # when a list, _rgb also appends the figure as SVG text (see plots_svg)


def _rgb(fig, plt):
    from . import render
    with render._MPL_LOCK:
        if _SVG_SINK is not None:
            import io
            buf = io.StringIO(); fig.savefig(buf, format="svg", facecolor=fig.get_facecolor()); _SVG_SINK.append(buf.getvalue())
        fig.canvas.draw()
        w, h = fig.canvas.get_width_height()
        a = np.frombuffer(fig.canvas.buffer_rgba(), np.uint8).reshape(h, w, 4)[..., :3].copy()
        plt.close(fig)
    return a


def plots_svg(result):
    """[(title, svg_text, explanation)] — vector versions of `plots(result)`."""
    global _SVG_SINK
    _SVG_SINK = []
    try:
        pl = plots(result)
        svgs = list(_SVG_SINK)
    finally:
        _SVG_SINK = None
    return [(t, svg, ex) for (t, _rgb_, ex), svg in zip(pl, svgs)]


def _legend(ax):
    ax.legend(facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="best")


def _note(ax, text, color=_GOOD, loc="tr"):
    x, y, ha, va = {"tr": (0.97, 0.92, "right", "top"), "br": (0.97, 0.08, "right", "bottom"),
                    "tl": (0.03, 0.92, "left", "top")}[loc]
    ax.text(x, y, text, transform=ax.transAxes, color=color, fontsize=9, ha=ha, va=va, fontweight="bold")


def _vel(result):
    if result.kind in ("lbm", "spectral", "porous"):
        return result.raw
    return result.hints.get("vel")


def _curl(ux, uy, dx=1.0):
    return np.gradient(uy, dx, axis=1) - np.gradient(ux, dx, axis=0)


def _tunit(result):
    return result.hints.get("time_unit", "frame")


def _times(result):
    return np.asarray(result.times, float)


# ═════════════════════════════ measurements ═════════════════════════════
def _peak_frequency(sig, dt, min_cycles=6):
    """Dominant frequency of a signal sampled every `dt` (Hann window, parabolic peak
    refinement). Returns (f, ok, reason): ok=False when the record holds fewer than
    `min_cycles` oscillations of the detected peak, i.e. the estimate is not meaningful."""
    sig = np.asarray(sig, float); n = len(sig)
    if n < 32:
        return 0.0, False, "fewer than 32 samples"
    sig = sig - sig.mean()
    t = np.arange(n) * dt
    sig = sig - np.polyval(np.polyfit(t, sig, 1), t)                # remove a linear drift
    win = np.hanning(n); sp = np.abs(np.fft.rfft(sig * win)); fr = np.fft.rfftfreq(n, d=dt)
    if len(sp) < 4 or not np.isfinite(sp).all():
        return 0.0, False, "no spectrum"
    k = int(np.argmax(sp[1:]) + 1)
    if 1 <= k < len(sp) - 1:                                           # parabolic interpolation
        a, b, c = np.log(sp[k - 1] + 1e-30), np.log(sp[k] + 1e-30), np.log(sp[k + 1] + 1e-30)
        d = 0.5 * (a - c) / (a - 2 * b + c) if (a - 2 * b + c) != 0 else 0.0
        f = fr[k] + d * (fr[1] - fr[0])
    else:
        f = fr[k]
    cycles = f * n * dt
    if cycles < min_cycles:
        return float(f), False, f"only {cycles:.1f} oscillation cycles in the record (need ≥ {min_cycles})"
    if sp[k] < 3.0 * np.median(sp[1:]):
        return float(f), False, "no clear spectral peak"
    return float(f), True, ""


def _wind_series(result):
    """Probe signal (every solver step) or, failing that, the frame-sampled transverse velocity."""
    h = result.hints
    if "probe_uy" in h and len(h["probe_uy"]) > 32:
        t = np.asarray(h["probe_t"], float); v = np.asarray(h["probe_uy"], float)
        keep = t >= 0.2 * t[-1]                                        # drop the start-up transient
        return t[keep], v[keep], "wake probe, sampled every lattice step"
    vel = result.raw; ny, nx = vel[0][0].shape
    ix = int(min(nx - 2, h.get("probe_x", int(0.62 * nx)))); jy = int(h.get("probe_y", ny // 2))
    return _times(result), np.array([uy[jy, ix] for _ux, uy in vel]), "animation frames (sparse)"


def _wake_drag(result):
    """Wake-survey drag coefficient (approximate): C_d ≈ (2/D) ∫ (u/U)(1 − u/U) dy at the probe
    plane, with u clipped to [0, U]. Clipping removes the faster bypass flow beside the wake, so
    this is an estimate of the momentum deficit, not a boundary-force integration."""
    vel = result.raw; h = result.hints
    ny, nx = vel[0][0].shape
    U = float(h.get("U", 0.1)) or 0.1
    D = max(1.0, float(h.get("D", ny * 0.2)))
    xp = int(min(nx - 2, h.get("probe_x", int(0.62 * nx))))
    cds = []
    for ux, _uy in vel:
        u = np.clip(ux[:, xp], 0.0, U)
        cds.append(2.0 * float(np.sum(u * (U - u))) / (U * U * D))
    return np.array(cds), U, D, xp


def _circulation(ux, uy, mask):
    rows = np.where(np.any(mask, axis=1))[0]; cols = np.where(np.any(mask, axis=0))[0]
    if not len(rows) or not len(cols):
        return 0.0, 1.0
    m = 8
    j0 = max(1, rows.min() - m); j1 = min(mask.shape[0] - 2, rows.max() + m)
    i0 = max(1, cols.min() - m); i1 = min(mask.shape[1] - 2, cols.max() + m)
    # Γ = ∮ u·dl taken counter-clockwise (y up): bottom +x, right +y, top −x, left −y.
    # Aerodynamics counts CLOCKWISE circulation as positive (L = ρ U Γ_cw gives upward lift
    # for a nose-up airfoil in left-to-right flow), so the sign is flipped here: the returned
    # Γ is positive when the lift is upward.
    gamma_ccw = (float(np.sum(ux[j0, i0:i1])) + float(np.sum(uy[j0:j1, i1]))
                 - float(np.sum(ux[j1, i0:i1])) - float(np.sum(uy[j0:j1, i0])))
    chord = float(cols.max() - cols.min() + 1)
    return -gamma_ccw, chord


def _ke_enstrophy(result):
    """Mean kinetic energy per unit mass ½⟨|u|²⟩ and enstrophy ½⟨ω²⟩ per frame
    (incompressible kinds). Units: velocity² and 1/time² of the solver."""
    vel = _vel(result); dx = float(result.hints.get("dx", 1.0))
    if not vel:
        return None, None
    ke = np.array([0.5 * float(np.mean(ux * ux + uy * uy)) for ux, uy in vel])
    ens = np.array([0.5 * float(np.mean(_curl(ux, uy, dx) ** 2)) for ux, uy in vel])
    return ke, ens


def metrics(result):
    """Scalar measurements for this result (numbers only; see explanations in `plots`)."""
    m = {}
    try:
        k = result.kind; h = result.hints
        if k == "porous":
            m["permeability_cells2"] = float(h.get("permeability", 0.0))
            m["porosity"] = float(h.get("porosity", 0.0))
        elif k == "tracer":
            m["peclet"] = float(h.get("peclet", 0.0))
            m["porosity"] = float(h.get("porosity") or 0.0)
            bt = np.asarray(h.get("breakthrough", []), float)
            t = _times(result)
            if bt.size and t.size == bt.size and bt.max() > 0:
                half = bt.max() * 0.5
                i = int(np.argmax(bt >= half))
                if bt[i] >= half:
                    m["arrival_time_t50"] = float(t[i])
            var = np.asarray(h.get("variance_cells2", []), float)
            # A pulse has a plume, and the growth of its variance is a dispersion measurement. A
            # steady supply does not: the tracer fills a growing part of the sample, so this number
            # rises even when there is nothing to disperse it. Uniform flow through a sample with no
            # grains at all, where mechanical dispersion is exactly zero, reports thousands of times
            # the molecular value. There is no coefficient to report in that case, so none is.
            if var.size > 4 and t.size == var.size and h.get("injection") != "continuous":
                half = _tracer_window(h, t)
                sl = np.polyfit(t[half], var[half], 1)[0]
                m["dispersion_cells2_per_step"] = float(sl / 2.0)
                dm = float(h.get("dm", 0.0))
                if dm > 0:
                    m["dispersion_over_molecular"] = float(sl / 2.0 / dm)
            inj = np.asarray(h.get("mass_in", []), float)
            bal = np.asarray(h.get("balance", []), float)
            if inj.size and bal.size and inj[-1] > 0:      # injected − left − still inside, relative
                m["tracer_mass_balance"] = float(abs(bal[-1]) / inj[-1])
            out = np.asarray(h.get("mass_out", []), float)
            if out.size and inj.size and inj[-1] > 0:
                m["fraction_left_the_sample"] = float(out[-1] / inj[-1])
            # How well the frozen-flow approximation holds, and how much of the requested
            # experiment actually ran. Both are measurements, so both are reported.
            if h.get("pore_reynolds") is not None:
                m["pore_reynolds"] = float(h["pore_reynolds"])
            if h.get("crossings_run") is not None:
                m["pore_volume_crossings"] = float(h["crossings_run"])
        elif k == "lbm":
            obs = h.get("obstacle", "Cylinder")
            t, sig, _src = _wind_series(result)
            dt = float(np.median(np.diff(t))) if len(t) > 2 else 1.0
            f, ok, _why = _peak_frequency(sig, dt)
            D, U = h.get("D"), h.get("U")
            if ok and D and U and obs != "Your text":
                m["strouhal"] = float(f * D / U)
            m["shedding_frequency_per_step"] = float(f) if ok else float("nan")
            cds, U_, D_, _xp = _wake_drag(result)
            m["cd_wake_approx"] = float(np.mean(cds[len(cds) // 2:]))
            if obs == "Airfoil" and result.mask is not None:
                gam = [_circulation(ux, uy, result.mask)[0] for ux, uy in result.raw]
                _g, chord = _circulation(result.raw[-1][0], result.raw[-1][1], result.mask)
                cl = 2.0 * np.array(gam) / (U_ * max(chord, 1.0))
                m["cl_circulation"] = float(np.mean(cl[len(cl) // 2:]))
        elif k == "spectral":
            ke, ens = _ke_enstrophy(result)
            m["ke_final"] = float(ke[-1]); m["ke_initial"] = float(ke[0]); m["enstrophy_final"] = float(ens[-1])
            m["ke_drift_rel"] = float((ke[-1] - ke[0]) / (ke[0] + 1e-30))
        elif k == "ns":
            mode = h.get("ns_mode", "smoke")
            if mode == "rb":
                nu_ = _rb_fluxes(result)
                m["nusselt"] = float(nu_["Nu"])
            elif mode == "rt":
                w = _rt_width(result)
                m["mixing_width_final_frac"] = float(w[-1])
            else:
                ke, ens = _ke_enstrophy(result)
                if ke is not None:
                    m["ke_final"] = float(ke[-1])
        elif k == "density":
            if h.get("mode") == "blast":
                R = _shock_radius(result)
                m["shock_radius_final_cells"] = float(R[-1])
            elif h.get("mode") == "sod":
                from . import validate
                raw = result.raw; nx = raw[0].shape[1]; x = (np.arange(nx) + 0.5) / nx
                ex_r, ex_u, _p = validate.exact_sod_full(x, float(result.times[-1]) / nx)
                m["sod_err_rho"] = float(np.mean(np.abs(raw[-1].mean(axis=0) - ex_r)))
                if h.get("vel"):
                    m["sod_err_u"] = float(np.mean(np.abs(h["vel"][-1][0].mean(axis=0) - ex_u)))
            else:
                ke = _compressible_ke(result)
                m["ke_final"] = float(ke[-1])
        elif k == "particles":
            ke, npart = _sph_energy(result)
            m["ke_peak"] = float(ke.max()); m["ke_final"] = float(ke[-1]); m["particles_final"] = int(npart[-1])
        elif k == "field":
            if str(h.get("label", "")).startswith("V"):
                m["pattern_coverage_pct"] = float(np.mean(result.raw[-1] > 0.25) * 100)
            else:
                m["dye_variance_final"] = float(np.var(result.raw[-1])); m["dye_variance_initial"] = float(np.var(result.raw[0]))
        elif k == "quantum":
            norm = h.get("norm")
            if norm:
                m["norm_drift"] = float(max(abs(x - 1) for x in norm))
    except Exception:                       # noqa: BLE001 — metrics must never break the UI
        pass
    return {k: v for k, v in m.items() if v is not None}


def series(result):
    """Time series (first key = time axis) for CSV export and plots."""
    out = {}
    try:
        t = _times(result).tolist(); k = result.kind; h = result.hints
        out["time"] = t
        if k in ("lbm", "spectral", "porous") or (k == "ns" and h.get("vel")):
            ke, ens = _ke_enstrophy(result)
            if ke is not None:
                out["kinetic_energy_per_mass"] = ke.tolist(); out["enstrophy"] = ens.tolist()
        if k == "tracer":
            for key, name in (("breakthrough", "outlet_concentration"), ("variance_cells2", "plume_variance_cells2"),
                              ("centre_cells", "plume_centre_cells"), ("mass", "tracer_mass")):
                v = h.get(key)
                if v is not None and len(v) == len(t):
                    out[name] = [float(x) for x in v]
        if k == "lbm":
            cds, *_ = _wake_drag(result); out["cd_wake_approx"] = cds.tolist()
            if "probe_uy" in h:
                out = {"probe_step": np.asarray(h["probe_t"]).tolist(), "probe_uy": np.asarray(h["probe_uy"]).tolist(), **out}
        if k == "ns" and h.get("ns_mode") == "rt":
            out["mixing_width_frac"] = _rt_width(result).tolist()
        if k == "density" and h.get("mode") == "blast":
            out["shock_radius_cells"] = _shock_radius(result).tolist()
        if k == "particles":
            ke, npart = _sph_energy(result); out["kinetic_energy_J_per_m"] = ke.tolist(); out["particles"] = npart.tolist()
            for name, vals in _sph_scene_series(result).items():
                out[name] = vals
        if k == "field":
            out["variance"] = [float(np.var(s)) for s in result.raw]
        if k == "quantum" and h.get("norm"):
            out["norm"] = [float(x) for x in h["norm"]]
    except Exception:                       # noqa: BLE001
        pass
    return out


# ───────────── helpers shared by metrics and plots ─────────────
def _rt_width(result):
    """Mixing-layer width: fraction of the height where the horizontally averaged
    NORMALISED scalar lies in (0.1, 0.9). The scalar is normalised by the initial
    heavy/light values, so the unmixed initial state has (near) zero width."""
    raw = result.raw; ny = raw[0].shape[0]
    p0 = raw[0].mean(axis=1); lo, hi = float(p0.min()), float(p0.max())
    span = max(hi - lo, 1e-9)
    w = []
    for s in raw:
        prof = (s.mean(axis=1) - lo) / span
        mix = np.where((prof > 0.1) & (prof < 0.9))[0]
        w.append((mix.max() - mix.min() + 1 if len(mix) else 0) / ny)
    return np.array(w)


def _rb_fluxes(result):
    """Horizontally averaged heat fluxes at the final frame, in the solver's units:
    conductive −κ d⟨T⟩/dz, convective ⟨v T⟩ (v = vertical velocity), and the Nusselt
    number Nu = (total flux) / (κ ΔT / H), with ΔT the plate difference and H the
    layer height, using the layer average of the total flux."""
    raw = result.raw; vel = result.hints.get("vel"); kappa = float(result.hints.get("kappa", 0.02))
    ny, nx = raw[0].shape; T = raw[-1]
    Tbar = T.mean(axis=1); z = np.arange(ny, dtype=float)
    cond = -kappa * np.gradient(Tbar, z)
    conv = np.zeros(ny)
    if vel:
        _ux, uy = vel[-1]; conv = np.mean(uy * T, axis=1)
    total = cond + conv
    dT = float(abs(Tbar[0] - Tbar[-1])) or 1.0; H = float(ny - 1)
    Nu = float(np.mean(total[1:-1])) / (kappa * dT / H) if kappa > 0 else float("nan")
    return {"z": z / H, "T0": raw[0].mean(axis=1), "T": Tbar, "cond": cond, "conv": conv, "total": total,
            "Nu": Nu, "kappa": kappa, "dT": dT, "H": H}


def _shock_radius(result):
    """Shock-front radius per frame (cells) from the azimuthally averaged density profile:
    the radius of the steepest outward density rise (max dρ/dr) — one robust number per
    frame instead of the single strongest pixel. Solid cells are excluded; in the city
    scene reflected fronts are not separated (see the explanation)."""
    raw = result.raw; ny, nx = raw[0].shape; h = result.hints
    cx = nx * (0.20 if h.get("building") else 0.5); cy = ny * (0.14 if h.get("building") else 0.5)
    yy, xx = np.mgrid[0:ny, 0:nx]; rr = np.hypot(xx - cx, yy - cy)
    solid = h.get("solid")
    rmax = float(rr.max()); nb = int(max(24, min(nx, ny) // 2)); edges = np.linspace(0, rmax, nb + 1)
    bins = np.clip(np.digitize(rr.ravel(), edges) - 1, 0, nb - 1)
    valid = np.ones(rr.size, bool) if solid is None else ~np.asarray(solid).ravel()
    cnt = np.bincount(bins[valid], minlength=nb) + 1e-9
    out = []
    for rho in raw:
        prof = np.bincount(bins[valid], weights=rho.ravel()[valid], minlength=nb) / cnt
        d = np.gradient(prof, edges[:-1] + 0.5 * (edges[1] - edges[0]))
        d[cnt < 3] = 0
        k = int(np.argmax(np.abs(d)))
        out.append(0.5 * (edges[k] + edges[k + 1]))
    return np.array(out)


def _compressible_ke(result):
    """Total kinetic energy ½ Σ ρ|u|² per frame (code units, per unit cell area) — density
    is included, unlike the incompressible per-mass definition."""
    vel = result.hints.get("vel"); raw = result.raw
    if not vel:
        return np.zeros(len(raw))
    return np.array([0.5 * float(np.sum(r * (ux * ux + uy * uy))) for r, (ux, uy) in zip(raw, vel)])


def _sph_energy(result):
    """Kinetic energy ½ Σ m v² (J per metre of depth, m = ρ₀ dp² with ρ₀ = 1000 kg/m³)
    and the particle count per frame (the pour scene adds particles over time)."""
    dp = float(result.hints.get("dp", 0.04)); m = 1000.0 * dp * dp
    ke = np.array([0.5 * m * float(np.sum(d[:, 2] ** 2)) for d in result.raw])
    npart = np.array([len(d) for d in result.raw])
    return ke, npart


def _surface_at(d, x, Ly, half=0.08):
    """Free-surface height at x: the highest particle within ±half of x (m)."""
    sel = d[np.abs(d[:, 0] - x) < half]
    return float(sel[:, 1].max()) if len(sel) else 0.0


def _sph_scene_series(result):
    h = result.hints; sc = h.get("scene", "dam"); Lx, Ly = h.get("Lx", 1.0), h.get("Ly", 1.0); raw = result.raw
    out = {}
    if sc == "dam":
        out["front_x_m"] = [float(d[d[:, 1] < 0.12 * Ly][:, 0].max()) if (d[:, 1] < 0.12 * Ly).any() else 0.0 for d in raw]
    elif sc == "drop":
        out["crown_height_m"] = [float(d[:, 1].max()) for d in raw]
    elif sc == "slosh":
        out["left_wall_level_m"] = [_surface_at(d, 0.06 * Lx, Ly) for d in raw]
        out["right_wall_level_m"] = [_surface_at(d, 0.94 * Lx, Ly) for d in raw]
    elif sc == "pour":
        out["fill_height_m"] = [float(np.percentile(d[:, 1], 90)) if len(d) else 0.0 for d in raw]
    elif sc in ("waves", "ship"):
        for name, xf in (("gauge_1_m", 0.25), ("gauge_2_m", 0.5), ("gauge_3_m", 0.75)):
            out[name] = [_surface_at(d, xf * Lx, Ly) for d in raw]
        hull = h.get("hull")
        if hull is not None:
            out["hull_heave_m"] = [float(hp[:, 1].mean()) for hp in hull]
            out["hull_roll_deg"] = [float(np.degrees(np.arctan2(*np.polyfit(hp[:, 0], hp[:, 1], 1)[:1], 1.0))) for hp in hull]
    return out


# ═════════════════════════════ plots ═════════════════════════════
def _shedding(result):
    h = result.hints; obs = h.get("obstacle", "Cylinder"); out = []
    t, sig, src = _wind_series(result)
    dt = float(np.median(np.diff(t))) if len(t) > 2 else 1.0
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "transverse velocity v at the probe (lattice)", "Wake probe — side-force proxy")
    ax.plot(t, sig, color=_CYAN, lw=1.2); ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5)
    out.append(("Lift signal", _rgb(fig, plt),
                f"Transverse velocity at a point in the wake ({src}); its oscillation is the alternating "
                "side force of vortex shedding. Units: lattice velocity. Source: the solver's wake probe "
                "written every step, after the first 20 % of the run (start-up transient removed)."))
    f, ok, why = _peak_frequency(sig, dt)
    D, U = h.get("D"), h.get("U")
    win = np.hanning(len(sig)); sp = np.abs(np.fft.rfft((sig - sig.mean()) * win)); fr = np.fft.rfftfreq(len(sig), d=dt)
    fig, ax, plt = _new_ax("frequency (cycles per lattice step)", "amplitude", "Shedding spectrum → Strouhal number")
    ax.plot(fr, sp, color=_AMBER, lw=1.6); ax.set_xlim(0, max(fr[1:].min() * 4, min(fr.max(), 8 * f if f > 0 else fr.max())))
    st_txt = ""
    if ok and D and U and obs != "Your text":
        st = f * D / U; ax.axvline(f, color=_CYAN, lw=1.4, ls="--")
        ref = {"Cylinder": "reference 0.18–0.21 (circular cylinder, Re 100–300, unconfined)",
               "Square": "reference ≈ 0.13–0.15 (square, Re ≈ 100–300)"}.get(obs, "no reference for this shape")
        _note(ax, f"St = f·D/U = {st:.3f}")
        st_txt = (f" Measured St = {st:.3f}; {ref}. This tunnel has blockage D/H = {D / result.raw[0][0].shape[0]:.2f} "
                  "and periodic side walls, which raise St slightly compared with an unconfined body, so treat a "
                  "difference of a few hundredths as expected rather than as agreement or disagreement.")
    elif not ok:
        _note(ax, f"insufficient data: {why}", _WARN)
        st_txt = f" No Strouhal number is reported: {why}. Run longer to get more shedding cycles."
    out.append(("Strouhal spectrum", _rgb(fig, plt),
                "Fourier spectrum of the probe signal (Hann window). The peak frequency f made dimensionless "
                "with the reference length D and inflow speed U is the Strouhal number St = f·D/U. A value "
                "is only reported when the record holds at least six shedding cycles with a clear peak." + st_txt))
    return out


def _drag_plot(result, title, body):
    cds, U, D, xp = _wake_drag(result); t = _times(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "C_d (wake-deficit estimate)", title)
    ax.plot(t, cds, color=_CYAN, lw=2.0)
    mean_cd = float(np.mean(cds[len(cds) // 2:])); ax.axhline(mean_cd, color=_AMBER, lw=1.1, ls="--")
    _note(ax, f"mean C_d ≈ {mean_cd:.2f} (approximate)")
    return [(title, _rgb(fig, plt),
             f"APPROXIMATION: drag of the {body} estimated from the wake momentum deficit at one plane "
             f"(x = {xp} cells) with the velocity clipped to [0, U] — C_d ≈ (2/D)∫(u/U)(1−u/U)dy — "
             "normalised by the reference length D. It excludes the bypass flow and pressure terms, so "
             "it indicates trends (bigger wake → more drag) rather than a validated force coefficient. "
             "A boundary-force (momentum-exchange) evaluation is the quantitative route and is not implemented.")], mean_cd


def _airfoil(result):
    vel = result.raw; out = []
    gam = [_circulation(ux, uy, result.mask)[0] for ux, uy in vel]
    U = float(result.hints.get("U", 0.1)) or 0.1
    _g, chord = _circulation(vel[-1][0], vel[-1][1], result.mask)
    cl = 2.0 * np.array(gam) / (U * max(chord, 1.0)); t = _times(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "C_l = 2Γ/(U c)", "Lift from the bound circulation (Kutta–Joukowski)")
    ax.plot(t, cl, color=_CYAN, lw=2.0); ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5)
    clm = float(np.mean(cl[len(cl) // 2:])); _note(ax, f"mean C_l ≈ {clm:+.2f}")
    out.append(("Lift coefficient", _rgb(fig, plt),
                "Circulation Γ = ∮u·dl on a rectangle 8 cells outside the airfoil, with the aerodynamic sign "
                "convention (clockwise positive, so that L = ρ U Γ is upward for a nose-up airfoil in "
                "left-to-right flow); C_l = 2Γ/(U c) with c the chord in cells (Kutta–Joukowski). Positive angle "
                "of attack = leading edge up = positive C_l; a negative angle gives a negative C_l of similar "
                "magnitude (mirror test in tests/). The contour also captures shed vorticity passing through "
                "it, so the signal oscillates when the flow is unsteady."))
    dr, _ = _drag_plot(result, "Drag (wake-deficit estimate)", "airfoil")
    return out + dr


def _drafting(result):
    vel = result.raw; h = result.hints
    ny, nx = vel[0][0].shape; U = float(h.get("U", 0.1)) or 0.1
    jy = int(h.get("probe_y", ny // 2))
    ux = np.mean([f[0] for f in vel[len(vel) // 2:]], axis=0)
    line = ux[jy, :] / U
    solid = np.any(result.mask[max(0, jy - 4):jy + 4, :], axis=0)
    x = np.arange(nx)
    fig, ax, plt = _new_ax("x (cells)", "u / U", "Slipstream along the riders' line")
    ln = line.copy(); ln[solid] = np.nan
    ax.plot(x, ln, color=_CYAN, lw=2.0); ax.axhline(1.0, color=_MUTED, lw=0.8, ls="--")
    ax.fill_between(x, -0.4, 1.25, where=solid, color=_AMBER, alpha=0.25, step="mid")
    wake = line[(x > 0.30 * nx) & (x < 0.55 * nx) & ~solid]
    mn = float(np.nanmin(wake)) if len(wake) else 1.0
    _note(ax, f"minimum u/U ≈ {mn:.2f} in the gap", loc="br")
    ax.axhline(0, color=_MUTED, lw=0.8, alpha=0.5); ax.set_ylim(-0.4, 1.25)
    out = [("Slipstream profile", _rgb(fig, plt),
            "Streamwise velocity along the riders' centre line (riders shaded), averaged over the settled "
            "second half of the run and divided by the inflow speed U. The pocket of slow air behind the "
            "leader is what a following rider sits in. This is a 2-D silhouette at a modest Reynolds "
            "number: it shows the wake structure, not a real-world power saving.")]
    dr, _ = _drag_plot(result, "Combined drag of the pair (wake-deficit estimate)", "pair")
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
        body = "car silhouette" if obs == "F1 car" else "rider silhouette"
        dr, _ = _drag_plot(result, f"Drag of the {body} (wake-deficit estimate)", body)
        return dr + _shedding(result)[:1]
    return _shedding(result)


def _energy_plot(result, title, what):
    ke, ens = _ke_enstrophy(result)
    if ke is None:
        return []
    t = _times(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "½⟨|u|²⟩ (velocity²)", title)
    ax.plot(t, ke, color=_CYAN, lw=2.0, label="kinetic energy per unit mass")
    ax2 = ax.twinx(); ax2.plot(t, ens, color=_AMBER, lw=2.0, label="enstrophy ½⟨ω²⟩")
    ax2.tick_params(colors=_MUTED, labelsize=8); ax2.set_ylabel("½⟨ω²⟩ (1/time²)", color=_FG, fontsize=9)
    for s in ax2.spines.values():
        s.set_color(_GRID)
    lines = ax.get_lines() + ax2.get_lines(); ax.legend(lines, [l.get_label() for l in lines], facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="best")
    return [(title, _rgb(fig, plt),
             "Domain-averaged kinetic energy per unit mass ½⟨|u|²⟩ (left axis, absolute values) and enstrophy "
             "½⟨ω²⟩ (right axis) at every saved frame; ω = ∂v/∂x − ∂u/∂y by central differences. " + what)]


def _plume_rise(result):
    raw = result.raw; ny = raw[0].shape[0]; t = _times(result)
    hgt = np.array([(np.where(s.max(axis=1) > 0.15)[0].max() if (s.max(axis=1) > 0.15).any() else 0) for s in raw], float)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "plume top (cells)", "Buoyant plume rise")
    ax.plot(t, hgt, color=_CYAN, lw=2.0); ax.set_ylim(0, ny)
    out = [("Plume rise", _rgb(fig, plt),
            "Highest row where the scalar exceeds 0.15 (cells above the floor) at each saved frame. The "
            "scalar is the transported dye/temperature proxy, not a measured temperature.")]
    return out + _energy_plot(result, "Kinetic energy & enstrophy", "Both grow as the column rolls up into eddies.")


def _rt_mixing(result):
    w = _rt_width(result); t = _times(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "mixing-layer width / H", "Rayleigh–Taylor mixing-layer growth")
    ax.plot(t, w, color=_AMBER, lw=2.0)
    return [("Mixing width", _rgb(fig, plt),
             "Height fraction where the horizontally averaged scalar, normalised by its initial heavy and "
             "light values, lies between 0.1 and 0.9. The unmixed initial state therefore has near-zero width. "
             "Classical theory gives h ≈ α A g t² late in the mixing regime; this run uses a constant-density "
             "projection with density only in the buoyancy term (a Boussinesq-like approximation), so "
             "quantitative growth rates at high Atwood number are not established here.")]


def _rb_convection(result):
    f = _rb_fluxes(result); out = []
    fig, ax, plt = _new_ax("horizontally averaged temperature ⟨T⟩", "height z / H", "Temperature profile")
    ax.plot(f["T0"], f["z"], color=_MUTED, lw=1.5, ls="--", label="initial (conduction)")
    ax.plot(f["T"], f["z"], color=_CYAN, lw=2.0, label="final"); _legend(ax)
    out.append(("Temperature profile", _rgb(fig, plt),
                "Horizontally averaged temperature versus height at the first and last saved frames. Pure "
                "conduction keeps the linear profile; convection mixes the interior and confines the change "
                "to thin layers at the plates. T is the solver's dimensionless plate-to-plate temperature."))
    fig, ax, plt = _new_ax("heat flux (solver units)", "height z / H", "Heat flux budget at the final frame")
    ax.plot(f["cond"], f["z"], color=_MUTED, lw=1.6, label="conductive −κ d⟨T⟩/dz")
    ax.plot(f["conv"], f["z"], color=_AMBER, lw=2.0, label="convective ⟨v T⟩")
    ax.plot(f["total"], f["z"], color=_CYAN, lw=2.0, label="total"); ax.axvline(0, color=_MUTED, lw=0.8, alpha=0.6); _legend(ax)
    nu_txt = f"Nu ≈ {f['Nu']:.2f}" if np.isfinite(f["Nu"]) else "Nu undefined (κ = 0)"
    _note(ax, nu_txt)
    out.append(("Heat flux and Nusselt number", _rgb(fig, plt),
                f"Conductive flux −κ d⟨T⟩/dz (κ = {f['kappa']:g}), convective flux ⟨v T⟩ and their sum, all in "
                "solver units, at the final frame. The Nusselt number is the layer-averaged total flux divided "
                f"by the conduction flux κ ΔT/H of the motionless state ({nu_txt}); Nu = 1 means no convective "
                "transport. Onset for rigid, conducting plates is Ra ≈ 1708 (see derived quantities for Ra)."))
    return out


def _chimney_trajectory(result):
    raw = result.raw; ny, nx = raw[0].shape
    s = np.mean(raw[len(raw) // 2:], axis=0); sx = nx // 4
    xs, zs = [], []
    for i in range(sx, nx - 2):
        col = s[:, i]
        if col.sum() > 0.02 * ny:
            xs.append(i); zs.append(float(np.sum(np.arange(ny) * col) / (col.sum() + 1e-9)))
    fig, ax, plt = _new_ax("downwind distance x (cells)", "plume centre-line height z (cells)", "Bent-over plume trajectory")
    if xs:
        ax.plot(xs, zs, color=_CYAN, lw=2.2)
    ax.axvline(sx, color=_AMBER, lw=1.2, ls="--"); ax.text(sx + 2, 0.05 * ny, "stack", color=_AMBER, fontsize=8); ax.set_ylim(0, ny)
    return [("Plume trajectory", _rgb(fig, plt),
             "Scalar-weighted centre-line height of the time-averaged (second half) plume as a function of "
             "downwind distance, in cells. The height it levels off at is the plume rise; it falls as the "
             "crosswind strengthens relative to the buoyancy.")]


def _flame(result):
    raw = result.raw; ny = raw[0].shape[0]; t = _times(result)
    tip = np.array([(np.where(T.max(axis=1) > 0.3)[0].max() if (T.max(axis=1) > 0.3).any() else 0) for T in raw], float)
    out = []
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "flame-tip height (cells)", "Flame tip height")
    ax.plot(t, tip, color=_AMBER, lw=2.0)
    out.append(("Flame tip height", _rgb(fig, plt),
                "Highest row where the temperature proxy T(Z) exceeds 0.3, per saved frame. The tip "
                "oscillates as buoyant vortices are shed near the base; the source velocity at the wick is "
                "prescribed (see the scene notes)."))
    dt = float(np.median(np.diff(t))) if len(t) > 2 else 1.0
    f, ok, why = _peak_frequency(tip, dt, min_cycles=4)
    win = np.hanning(len(tip)); sp = np.abs(np.fft.rfft((tip - tip.mean()) * win)); fr = np.fft.rfftfreq(len(tip), d=dt)
    fig, ax, plt = _new_ax(f"frequency (cycles per {_tunit(result)})", "amplitude", "Flicker spectrum")
    ax.plot(fr, sp, color=_CYAN, lw=1.6)
    if ok:
        ax.axvline(f, color=_AMBER, lw=1.3, ls="--"); _note(ax, f"peak at {f:.3g}")
    else:
        _note(ax, f"insufficient data: {why}", _WARN)
    out.append(("Flicker spectrum", _rgb(fig, plt),
                "Spectrum of the tip-height record (sampled once per saved frame, so only frequencies below "
                "half the frame rate are resolved). A peak is reported only with ≥ 4 cycles in the record."))
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


def _blast(result):
    R = _shock_radius(result); t = _times(result); h = result.hints
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "shock radius (cells)", "Blast-wave expansion")
    ax.plot(t, R, color=_CYAN, lw=2.0)
    if len(t) > 3 and t[-1] > 0:
        # power-law fit R ∝ t^n on the second half (Sedov–Taylor: n = 1/2 in 2-D for a strong point blast)
        k = len(t) // 2; tt, rr = t[k:], R[k:]; ok = (tt > 0) & (rr > 0)
        if ok.sum() > 2:
            n = np.polyfit(np.log(tt[ok]), np.log(rr[ok]), 1)[0]; _note(ax, f"R ∝ t^{n:.2f} (late fit)")
    city = " Reflections off the towers and the ground are not separated from the incident front." if h.get("building") else ""
    return [("Shock radius", _rgb(fig, plt),
             "Radius of the steepest rise of the azimuthally averaged density around the burst point, per "
             "saved frame (cells; time in code units with the actual adaptive time step). A strong 2-D "
             "point blast follows the Sedov–Taylor law R ∝ t^½; this finite-pressure charge starts faster "
             "and bends toward that exponent as it sweeps up gas — the late-time fit is shown. Caveat: the "
             "gradient-based estimate can lock onto a strong contact surface or a reflected front instead of the "
             "leading shock; treat isolated jumps in the curve as detection artefacts." + city)]


def _sod(result):
    """Sod shock tube against the exact Riemann solution: density (and velocity when saved)."""
    from . import validate
    raw = result.raw; h = result.hints; nx = raw[0].shape[1]; t = _times(result)
    rho = raw[-1].mean(axis=0); x = (np.arange(nx) + 0.5) / nx
    tp = float(t[-1]) / nx                                  # code time → tube-length units
    ex_r, ex_u, ex_p = validate.exact_sod_full(x, tp)
    err_r = float(np.mean(np.abs(rho - ex_r)))
    fig, ax, plt = _new_ax("x / L", "density ρ", f"Sod shock tube at t = {tp:.3f}: density vs exact")
    ax.plot(x, ex_r, color=_MUTED, lw=1.6, ls="--", label="exact Riemann solution")
    ax.plot(x, rho, color=_CYAN, lw=1.8, label="solver"); _legend(ax); _note(ax, f"mean |Δρ| = {err_r:.4f}")
    out = [("Density vs exact", _rgb(fig, plt),
            "Row-averaged density along the tube at the final frame against the exact Riemann solution (Toro): "
            "left state (ρ, u, p) = (1, 0, 1), right (0.125, 0, 0.1), γ = 1.4, membrane at x = 0.5. From left: "
            "rarefaction fan, contact discontinuity, shock. The MUSCL/HLLC scheme smears the contact over a few "
            f"cells; the mean absolute density error is {err_r:.4f} at {nx} cells (first-order at discontinuities).")]
    vel = h.get("vel")
    if vel:
        u = vel[-1][0].mean(axis=0); err_u = float(np.mean(np.abs(u - ex_u)))
        fig, ax, plt = _new_ax("x / L", "velocity u", "Velocity vs exact")
        ax.plot(x, ex_u, color=_MUTED, lw=1.6, ls="--", label="exact"); ax.plot(x, u, color=_AMBER, lw=1.8, label="solver"); _legend(ax)
        _note(ax, f"mean |Δu| = {err_u:.4f}")
        out.append(("Velocity vs exact", _rgb(fig, plt),
                    "Row-averaged velocity against the exact solution: the plateau between the rarefaction tail and "
                    "the shock is the star-region velocity u* ≈ 0.927."))
    return out


def _bubble(result):
    ke = _compressible_ke(result); t = _times(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "½ Σ ρ|u|² (code units)", "Kinetic energy after the shock passes")
    ax.plot(t, ke, color=_CYAN, lw=2.0)
    return [("Kinetic energy", _rgb(fig, plt),
             "Total kinetic energy ½Σρ|u|² over the domain (density included, as required for a compressible "
             "flow), per saved frame. It jumps when the shock enters and keeps rising as baroclinic vorticity "
             "(∇ρ × ∇p) rolls the bubble up — the Richtmyer–Meshkov mechanism.")]


def _particles(result):
    h = result.hints; sc = h.get("scene", "dam"); t = _times(result); out = []
    ke, npart = _sph_energy(result)
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "kinetic energy (J per m of depth)", "Kinetic energy of the water")
    ax.plot(t, ke, color=_CYAN, lw=2.0)
    if npart.max() != npart.min():
        ax2 = ax.twinx(); ax2.plot(t, npart, color=_MUTED, lw=1.2, ls="--"); ax2.set_ylabel("particles", color=_FG, fontsize=9); ax2.tick_params(colors=_MUTED, labelsize=8)
    out.append(("Kinetic energy", _rgb(fig, plt),
                "½ Σ m v² over the fluid particles with m = ρ₀ dp² (ρ₀ = 1000 kg/m³), i.e. joules per metre "
                "of depth for this 2-D model. The particle count is shown when it changes (the pour scene "
                "adds particles over time)."))
    ss = _sph_scene_series(result)
    if sc == "dam":
        g, H = float(h.get("g", 9.81)), float(h.get("H", 2.0))
        fig, ax, plt = _new_ax("time (s)", "front position (m)", "Leading surge front")
        ax.plot(t, ss["front_x_m"], color=_AMBER, lw=2.0)
        ax.plot(t, np.minimum(h.get("Lx", 5.0), float(h.get("a", 1.0)) + 2 * np.sqrt(g * H) * t), color=_MUTED, lw=1.2, ls="--", label="Ritter dry-bed limit 2√(gH)")
        _legend(ax)
        out.append(("Surge front", _rgb(fig, plt),
                    "Position of the water front along the floor (highest x among particles below 0.12 Ly) versus "
                    "time, with the frictionless shallow-water bound x = a + 2√(gH)·t (Ritter). A real column "
                    "collapses vertically first, so the front lags this bound."))
    elif sc == "drop":
        fig, ax, plt = _new_ax("time (s)", "highest water (m)", "Crown height")
        ax.plot(t, ss["crown_height_m"], color=_AMBER, lw=2.0)
        out.append(("Crown height", _rgb(fig, plt),
                    "Highest particle over time: the blob's fall, the impact, the crown/jet rise and its collapse. "
                    "Two-dimensional water-blob impact without surface tension — not a resolved 3-D splash."))
    elif sc == "slosh":
        fig, ax, plt = _new_ax("time (s)", "free-surface level at the walls (m)", "Sloshing response")
        ax.plot(t, ss["left_wall_level_m"], color=_CYAN, lw=1.8, label="left wall"); ax.plot(t, ss["right_wall_level_m"], color=_AMBER, lw=1.8, label="right wall"); _legend(ax)
        out.append(("Wall run-up", _rgb(fig, plt),
                    "Water level next to each wall (highest particle within a narrow strip) versus time under the "
                    "oscillating side force. Sweep the forcing period to find the resonant response."))
    elif sc == "pour":
        fig, ax, plt = _new_ax("time (s)", "fill level (m, 90th percentile height)", "Filling the glass")
        ax.plot(t, ss["fill_height_m"], color=_AMBER, lw=2.0)
        out.append(("Fill level", _rgb(fig, plt), "Water level in the glass versus time as the stream pours in."))
    elif sc in ("waves", "ship"):
        fig, ax, plt = _new_ax("time (s)", "surface elevation (m)", "Wave gauges")
        for k, c in (("gauge_1_m", _CYAN), ("gauge_2_m", _AMBER), ("gauge_3_m", _GOOD)):
            ax.plot(t, ss[k], color=c, lw=1.6, label=k.replace("_m", "").replace("_", " ") + f" (x = {['0.25', '0.5', '0.75'][int(k[6]) - 1]} Lx)")
        _legend(ax)
        out.append(("Wave gauges", _rgb(fig, plt),
                    "Free-surface elevation at three fixed positions. The delay between gauges gives the wave "
                    "speed and wavelength; with a closed tank the reflected train returns from the right wall, "
                    "so late-time records mix incident and reflected waves. Flat bottom — no shoaling."))
        if "hull_heave_m" in ss:
            fig, ax, plt = _new_ax("time (s)", "heave (m) · roll (°)", "Hull motion")
            ax.plot(t, ss["hull_heave_m"], color=_CYAN, lw=1.8, label="heave (hull centroid height)")
            ax2 = ax.twinx(); ax2.plot(t, ss["hull_roll_deg"], color=_AMBER, lw=1.5, label="roll (°)"); ax2.tick_params(colors=_MUTED, labelsize=8)
            lines = ax.get_lines() + ax2.get_lines(); ax.legend(lines, [l.get_label() for l in lines], facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8)
            out.append(("Hull motion", _rgb(fig, plt),
                        "Heave and roll of the rigid hull from its particle positions. The hull is driven by contact "
                        "forces from the water, gravity and damping (not by a pressure integration)."))
    return out


def _tracer_window(h, t):
    """Frames to measure spreading over. The outlet is open, so once a good part of the plume has
    left the sample the variance of what remains is no longer the variance of the plume. Keep the
    frames until a fifth has left, then use the later half of those."""
    n = len(t)
    stop = n
    out = np.asarray(h.get("mass_out", []), float)
    inj = np.asarray(h.get("mass_in", []), float)
    if out.size == n and inj.size == n and inj[-1] > 0:     # stop once a fifth has left the sample
        gone = np.where(out > 0.2 * inj)[0]
        if gone.size:
            stop = int(gone[0])
    stop = max(4, min(stop, n))
    return slice(stop // 2, stop)


def _tracer_profile(result, i):
    """Pore-averaged concentration along the flow direction for frame i."""
    c = np.asarray(result.raw[i], float)
    fluid = ~np.asarray(result.mask, bool) if result.mask is not None else np.ones_like(c, bool)
    axis = result.hints.get("axis", "x")
    f = fluid.astype(float)
    num, den = ((c * f).sum(axis=0), f.sum(axis=0)) if axis == "x" else ((c * f).sum(axis=1), f.sum(axis=1))
    return np.divide(num, den, out=np.zeros_like(num), where=den > 0)


def _tracer(result):
    h = result.hints; t = _times(result); out = []
    unit = _tunit(result)
    bt = np.asarray(h.get("breakthrough", []), float)
    var = np.asarray(h.get("variance_cells2", []), float)
    dm = float(h.get("dm", 0.0)); dnum = float(h.get("numerical_diffusion", 0.0))
    pe = float(h.get("peclet", 0.0)); cont = h.get("injection") == "continuous"
    # Conditions under which these numbers are not the experiment they appear to be.
    _notes = []
    if h.get("flow_settled") is False:
        _notes.append("the flow had not settled when it was frozen")
    if float(h.get("pore_reynolds", 0.0)) > 1.0:
        _notes.append(f"the pore Reynolds number is {float(h['pore_reynolds']):.3g}, so this is not the "
                      f"creeping flow that holding the field fixed assumes")
    if h.get("truncated"):
        _notes.append(f"the step budget stopped the run after {float(h.get('crossings_run', 0.0)):.3g} of the "
                      f"{float(h.get('crossings_requested', 0.0)):.3g} pore-volume crossings asked for")
    _caveat = (" Treat this as qualitative: " + "; ".join(_notes) + ".") if _notes else ""

    # ── 1) breakthrough at the outlet ───────────────────────────────────────────────
    if bt.size == t.size and bt.size > 2:
        fig, ax, plt = _new_ax(f"time ({unit})", "outlet concentration c/c₀", "Breakthrough at the outlet")
        ax.plot(t, bt, color=_CYAN, lw=2.0)
        ax.set_ylim(0, max(1.02, float(bt.max()) * 1.1))
        t50 = None
        if bt.max() > 0:
            half = bt.max() * 0.5
            i = int(np.argmax(bt >= half))
            if bt[i] >= half:
                t50 = float(t[i])
                ax.axvline(t50, color=_AMBER, lw=1.2, ls="--", label=f"half of the peak at t = {t50:.3g}")
                _legend(ax)
        tc = float(h.get("t_cross", 0.0))
        out.append(("Breakthrough at the outlet", _rgb(fig, plt),
                    ("Flux-averaged concentration of the water leaving the sample, Σuc/Σu over the outlet face: "
                     "what a sampler at the end of a column measures, not a plain average over the last cells. The "
                     "outlet is open, so tracer leaves and never returns. " +
                     ("A steady supply is held at the inlet, so this is a front arriving and the curve climbs towards "
                      "1. " if cont else "A slug was released at the inlet, so the curve rises, peaks and decays; its "
                      "tail is the tracer held back in slow channels and dead ends. ") +
                     f"One pore-volume crossing at the mean advective speed takes about {tc:.3g} {unit}" +
                     (f", and half of the peak arrives at {t50:.3g}. " if t50 is not None else ". ") +
                     "Arrival earlier than the crossing time means the tracer found fast channels." + _caveat)))

    # ── 2) spreading: variance against time, slope = 2 D_eff ────────────────────────
    if var.size == t.size and var.size > 6 and not cont:
        fig, ax, plt = _new_ax(f"time ({unit})", "plume variance σ² (cells²)", "How fast the plume spreads")
        ax.plot(t, var, color=_GOOD, lw=2.0, label="measured")
        half = _tracer_window(h, t)
        slope = float(np.polyfit(t[half], var[half], 1)[0])
        deff = slope / 2.0
        ax.plot(t[half], np.polyval(np.polyfit(t[half], var[half], 1), t[half]), color=_AMBER, lw=1.4, ls="--",
                label=f"fit while the plume travels: D_eff = {deff:.2e}")
        if dm > 0:
            ax.plot(t, var[0] + 2 * dm * (t - t[0]), color=_MUTED, lw=1.2, ls=":",
                    label=f"molecular diffusion alone: D_m = {dm:.2e}")
        _legend(ax)
        ratio = deff / dm if dm > 0 else float("nan")
        trust = ("The measured spreading is above the numerical diffusion of the advection scheme, so it reflects "
                 "the pore-scale velocity field." if deff > 3 * dnum else
                 "Careful: the measured spreading is not far above the numerical diffusion of the advection scheme "
                 "(u·dx/2), so at this setting the number says more about the grid than about the rock. Raise the "
                 "resolution or lower the Péclet number.")
        out.append(("How fast the plume spreads", _rgb(fig, plt),
                    (f"Variance of the pore-averaged concentration profile along the flow. For pure diffusion it "
                     f"grows as 2·D_m·t; the slope of the measured curve, fitted while the plume is still "
                     f"inside the sample (the fit stops once a fifth has left through the open outlet), gives an "
                     f"effective spreading coefficient "
                     f"D_eff = {deff:.2e} cells²/step, which is {ratio:.0f} times the molecular value at Pe = {pe:g}. "
                     f"Spreading beyond the molecular value is mechanical dispersion, neighbouring channels "
                     f"carrying the tracer at different speeds, so long as it also stands clear of the scheme's "
                     f"own numerical diffusion, which here is about {dnum:.2e}. " + trust)))

    elif var.size == t.size and var.size > 6:
        fig, ax, plt = _new_ax(f"time ({unit})", "spread of the tracer σ² (cells²)",
                               "How far the tracer has spread")
        ax.plot(t, var, color=_GOOD, lw=2.0)
        out.append(("How far the tracer has spread", _rgb(fig, plt),
                    ("Second moment of the tracer along the flow, weighted by the tracer each slice holds. "
                     "With a steady supply this is not a dispersion measurement, and none is reported: the "
                     "tracer fills a growing part of the sample, so this curve rises even when there is "
                     "nothing to disperse it. A uniform flow through a sample with no grains at all, where "
                     "mechanical dispersion is exactly zero, still produces a rising curve here. To measure "
                     "dispersion, release a pulse instead and read the spreading plot there; what this "
                     "experiment measures is the breakthrough curve above.")))

    # ── 3) profiles along the flow at three times ───────────────────────────────────
    n = result.nframes
    if n >= 3:
        fig, ax, plt = _new_ax("distance along the flow (cells)", "concentration c/c₀",
                               "The plume as it crosses the sample")
        for i, col in ((0, _MUTED), (n // 2, _CYAN), (n - 1, _AMBER)):
            ax.plot(_tracer_profile(result, i), color=col, lw=1.8, label=f"t = {t[i]:.3g}")
        _legend(ax)
        out.append(("The plume as it crosses the sample", _rgb(fig, plt),
                    ("Concentration averaged across the sample at each position along the flow, pore cells only, at "
                     "the start, the middle and the end of the run. A symmetric hump means diffusion dominates; a "
                     "steep front with a long tail behind it means the velocity field is doing the spreading.")))
    return out


def _porous(result):
    h = result.hints
    phi = h.get("porosity", 0.6); k = h.get("permeability", 0.0); d = 2.0 * h.get("grain", 12)
    P = np.linspace(0.35, 0.9, 120); kc = P ** 3 * d * d / (180.0 * (1.0 - P) ** 2)
    fig, ax, plt = _new_ax("porosity φ", "permeability k (lattice cells²)", "Permeability of this sample")
    ax.plot(P, kc, color=_MUTED, lw=1.6, ls="--", label="Kozeny–Carman (empirical, 3-D packed beds; orientation only)")
    ax.scatter([phi], [max(k, 1e-9)], color=_AMBER, s=90, zorder=5, edgecolor="#1a1a1a", label=f"this run: φ = {phi:.2f}, k = {k:.2f}")
    ax.set_yscale("log"); _legend(ax)
    return [("Permeability (Darcy)", _rgb(fig, plt),
             "k = ν U_D / g from the final frame: ν = (τ − ½)/3, U_D the superficial velocity (flow averaged over "
             "the whole sample including solid cells) and g the body force per unit mass (Guo forcing; "
             f"here g = {h.get('force', 0):.1e}). A pore-average velocity ⟨u⟩_fluid = U_D/φ is reported separately "
             f"({h.get('mean_ux_pore', 0) if h.get('mean_ux_pore') is not None else 'n/a'}). One point next to an "
             "empirical curve does not establish agreement: the Kozeny–Carman line is for 3-D packed beds and is "
             "drawn for orientation. To check Darcy behaviour, sweep the porosity or the seed (same φ, different "
             "connectivity) with the sweep tool; the run reports k from the final state and should be run long "
             "enough for the readout to have settled (increase Duration and compare).")]


def _field(result):
    raw = result.raw; label = str(result.hints.get("label", "")); t = _times(result)
    if label.startswith("V"):
        cov = np.array([float(np.mean(s > 0.25)) for s in raw]) * 100.0
        fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "area with V > 0.25 (%)", "Pattern coverage")
        ax.plot(t, cov, color=_GOOD, lw=2.0); ax.set_ylim(0, max(60, cov.max() * 1.1))
        return [("Pattern coverage", _rgb(fig, plt),
                 "Percentage of the domain where the V concentration exceeds 0.25, per saved frame. Note that "
                 "the scheme clips U and V to [0, 1] each step; a clip that activates is a numerical intervention, "
                 "not part of the Gray–Scott model.")]
    var = np.array([float(np.var(s)) for s in raw])
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "dye variance ⟨c²⟩ − ⟨c⟩²", "Mixing of the dye")
    ax.plot(t, var, color=_CYAN, lw=2.0)
    kap = result.hints.get("kappa", None); stir = result.hints.get("stir", 1.0)
    return [("Dye mixing", _rgb(fig, plt),
             "Variance of the dye concentration over the domain (absolute). Stirring alone cannot reduce the "
             "variance of a conserved scalar; the decay seen here comes from molecular diffusion "
             f"(κ = {kap}) plus the numerical diffusion of the bilinear semi-Lagrangian scheme once "
             f"filaments thin below the grid. Compare stirring strength {stir} with 0 (diffusion only) and "
             "κ = 0 (stirring only) to separate the two.")]


def _quantum(result):
    norm = result.hints.get("norm")
    if not norm:
        return []
    t = _times(result); closed = result.hints.get("scene") == "harmonic"
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "total probability ∫|ψ|²", "Probability conservation")
    ax.plot(t, norm, color=_CYAN, lw=2.0); ax.axhline(1.0, color=_MUTED, lw=0.8, ls="--")
    if closed:
        ax.set_ylim(0.999, 1.001); _note(ax, f"drift {max(abs(x - 1) for x in norm):.0e}")
        ex = "Closed harmonic well: the split-step scheme is unitary, so the norm should stay 1 to round-off."
    else:
        ax.set_ylim(0, 1.05); _note(ax, "open system: probability leaves through the absorber", _MUTED)
        ex = "Open scattering set-up: probability leaves through the absorbing border, so the norm decays."
    return [("Probability conservation", _rgb(fig, plt), ex)]


def _spectral(result):
    ke, ens = _ke_enstrophy(result); t = _times(result); h = result.hints
    fig, ax, plt = _new_ax(f"time ({_tunit(result)})", "½⟨|u|²⟩", "2-D turbulence: energy & enstrophy")
    ax.plot(t, ke, color=_CYAN, lw=2.0, label="kinetic energy per unit mass")
    if h.get("init") == "Taylor–Green" and h.get("nu") is not None:
        ax.plot(t, ke[0] * np.exp(-4.0 * float(h["nu"]) * (t - t[0])), color=_GOOD, lw=1.2, ls="--", label="analytical E₀·exp(−4νt)")
    ax2 = ax.twinx(); ax2.plot(t, ens, color=_AMBER, lw=2.0, label="enstrophy ½⟨ω²⟩"); ax2.tick_params(colors=_MUTED, labelsize=8)
    lines = ax.get_lines() + ax2.get_lines(); ax.legend(lines, [l.get_label() for l in lines], facecolor=_BG, edgecolor=_GRID, labelcolor=_FG, fontsize=8, loc="best")
    extra = (" The Taylor–Green vortex decays as exp(−4νt) for wavenumber 1 in a 2π box; the dashed line is that "
             "prediction.") if h.get("init") == "Taylor–Green" else \
            " In decaying 2-D turbulence the energy is nearly conserved while enstrophy falls as small eddies merge (inverse cascade)."
    return [("Energy & enstrophy", _rgb(fig, plt),
             "Domain-averaged kinetic energy per unit mass and enstrophy (absolute, nondimensional units, L = 2π). "
             "Time integration is explicit RK4, so with ν = 0 energy is conserved to truncation error, not exactly." + extra)]


def plots(result):
    """Return [(title, rgb ndarray, explanation), …] of diagnostics for this result."""
    try:
        k = result.kind
        if k == "quantum":
            return _quantum(result)
        if k == "tracer":
            return _tracer(result)
        if k == "porous":
            return _porous(result)
        if k == "lbm":
            return _wind_tunnel(result)
        if k == "spectral":
            return _spectral(result)
        if k == "ns":
            return _ns(result)
        if k == "density":
            mode = result.hints.get("mode")
            return _blast(result) if mode == "blast" else (_sod(result) if mode == "sod" else _bubble(result))
        if k == "particles":
            return _particles(result)
        if k == "field":
            return _field(result)
    except Exception as e:                  # noqa: BLE001 — a failed diagnostic must not break the app
        return [("Diagnostics unavailable", _unavailable_plot(f"{type(e).__name__}: {e}"),
                 f"The diagnostic for this run could not be computed ({type(e).__name__}: {e}). The simulation "
                 "result itself is unaffected; probes, profiles and exports still work.")]
    return [("No diagnostics", _unavailable_plot("no diagnostic is defined for this kind of result"),
             "No measurement is defined for this kind of result yet; use the probe and profile tools.")]


def _unavailable_plot(msg):
    fig, ax, plt = _new_ax("", "", "Diagnostics unavailable")
    ax.text(0.5, 0.5, msg, transform=ax.transAxes, color=_WARN, ha="center", va="center", fontsize=9, wrap=True)
    return _rgb(fig, plt)
