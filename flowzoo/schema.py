"""Parameter schema: validation, coercion and derived quantities for every exhibit.

Each parameter descriptor in `engine.EXHIBITS[name]["params"]` is a dict with:

    name, label, type ("float" | "int" | "choice" | "str"), default, group, help
    min / max      recommended experiment range (soft: outside → warning, run allowed
                   only when `allow_outside=True`, i.e. the UI's advanced mode)
    hard_min / hard_max   numerical constraints of the solver (hard: outside → error)
    units          string, e.g. "lattice units", "m", "°" (absent = dimensionless)
    when           (control, [values]) — shown/used only when control ∈ values
    advanced       True → hidden in the approachable mode
    fixed          what is held fixed when this control changes (shown as help)
    choices        for "choice" types

`validate(exhibit, params)` returns a Validation with the cleaned parameter dict,
hard `errors` (the run must not start), soft `warnings` (outside the recommended
range) and `applied` notes (values the geometry forced, e.g. a minimum width).
`derived(exhibit, params)` lists the quantities the runner will actually use
(viscosity, lattice Mach number, characteristic length, particle count …) so the
user can see what a control does before running.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np


@dataclass
class Validation:
    params: dict
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    applied: list = field(default_factory=list)

    @property
    def ok(self):
        return not self.errors

    def as_dict(self):
        return {"ok": self.ok, "params": self.params, "errors": list(self.errors),
                "warnings": list(self.warnings), "applied": list(self.applied)}


def _specs(exhibit):
    from . import engine
    if exhibit not in engine.EXHIBITS:
        raise KeyError(f"unknown exhibit: {exhibit}")
    return engine.EXHIBITS[exhibit]["params"]


def active(exhibit, params):
    """Descriptors whose `when` dependency is satisfied by `params` (in spec order)."""
    specs = _specs(exhibit)
    full = {q["name"]: q["default"] for q in specs}; full.update(params or {})
    out = []
    for q in specs:
        w = q.get("when")
        if w and full.get(w[0]) not in list(w[1]):
            continue
        out.append(q)
    return out


def _finite(x):
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def validate(exhibit, params, allow_outside=False):
    """Validate + coerce user parameters (see module docstring)."""
    specs = _specs(exhibit)
    known = {q["name"]: q for q in specs}
    v = Validation(params={})
    params = dict(params or {})
    for k in params:
        if k not in known:
            v.errors.append(f"unknown parameter: {k}")
    act = {q["name"] for q in active(exhibit, params)}
    for q in specs:
        name = q["name"]; t = q.get("type", "float")
        raw = params.get(name, q["default"])
        if name not in act:                       # hidden by a dependency: keep the default, ignore input
            v.params[name] = q["default"]
            continue
        lab = q.get("label", name)
        if t == "choice":
            if raw not in q["choices"]:
                v.errors.append(f"{lab}: {raw!r} is not one of {q['choices']}")
                raw = q["default"]
            v.params[name] = raw
            continue
        if t == "str":
            s = "" if raw is None else str(raw)
            mx = q.get("max_len", 40)
            if len(s) > mx:
                v.warnings.append(f"{lab}: text longer than {mx} characters is truncated")
                s = s[:mx]
            if q.get("required", True) and not s.strip():
                v.errors.append(f"{lab}: enter some text")
            v.params[name] = s
            continue
        # numeric
        if isinstance(raw, str):
            raw = raw.strip().replace(",", ".")
        if raw is None or raw == "" or not _finite(raw):
            v.errors.append(f"{lab}: enter a number"); v.params[name] = q["default"]
            continue
        val = float(raw)
        if t == "int":
            if abs(val - round(val)) > 1e-9:
                v.applied.append(f"{lab}: rounded to {int(round(val))}")
            val = int(round(val))
        hmin, hmax = q.get("hard_min"), q.get("hard_max")
        if hmin is not None and val < hmin:
            v.errors.append(f"{lab}: must be ≥ {hmin}{_u(q)} (solver limit)")
        if hmax is not None and val > hmax:
            v.errors.append(f"{lab}: must be ≤ {hmax}{_u(q)} (solver limit)")
        lo, hi = q.get("min"), q.get("max")
        outside = (lo is not None and val < lo) or (hi is not None and val > hi)
        if outside:
            msg = f"{lab}: {val:g}{_u(q)} is outside the recommended range {lo:g} – {hi:g}"
            if allow_outside:
                v.warnings.append(msg + " (allowed in advanced mode)")
            else:
                v.errors.append(msg + " — enable advanced mode to explore beyond it")
        v.params[name] = val
    return v


def _u(q):
    u = q.get("units")
    return f" {u}" if u else ""


def check_presets():
    """Every shipped catalogue preset must pass the same validation as user input."""
    from . import catalog
    bad = []
    for s in catalog.SCENES:
        r = validate(s["exhibit"], s["preset"])
        if not r.ok:
            bad.append((s["key"], r.errors))
    return bad


# ----------------------------------------------------------------- derived quantities
def derived(exhibit, params):
    """Quantities the runner will use, computed the same way the runner does.

    Advisory only: this never raises. If a readout cannot be computed the list
    carries one item explaining why, so a completed run is never invalidated by
    a readout problem."""
    try:
        return _derived(exhibit, params)
    except Exception as e:                       # noqa: BLE001
        return [{"label": "derived quantities unavailable", "value": f"{type(e).__name__}: {e}", "units": "",
                 "note": "the simulation itself is unaffected"}]


def _fmt_ratio(num, den, digits=3):
    return f"{num / den:.{digits}g}" if den else "undefined (division by zero)"


def _derived(exhibit, params):
    from . import engine
    p = validate(exhibit, params, allow_outside=True).params
    s = engine._res(p); dur = engine._durv(p); out = []

    def add(label, value, units="", note=""):
        out.append({"label": label, "value": value, "units": units, "note": note})

    if exhibit == "Wind Tunnel":
        nx, ny = int(900 * s), int(300 * s)
        Re = float(p["reynolds"]); U = float(p["speed"]); obs = p["obstacle"]
        D = max(8.0, ny * float(p["size"]))
        if obs == "Your text":
            D = ny * 0.34
        elif obs == "F1 car":
            D = 0.34 * ny * 1.05
        elif obs == "Cyclist":
            D = 0.6 * ny * 0.42
        elif obs == "Peloton (drafting)":
            D = 0.6 * ny * 0.38
        tau = 0.5 + 3 * (U * D / Re); nu = (tau - 0.5) / 3
        add("grid", f"{nx} × {ny}", "cells")
        add("reference length D", f"{D:.1f}", "cells", "chord = 2.6 D for the airfoil; fixed by the silhouette for vehicles/text")
        add("viscosity ν = (τ−½)/3", f"{nu:.2e}", "lattice", "recomputed so Re = U·D/ν holds at the chosen speed")
        add("relaxation time τ", f"{tau:.4f}", "", "τ close to 0.5 is under-resolved (use a lower Re or higher speed)")
        add("lattice Mach U/c_s", f"{U * math.sqrt(3):.3f}", "", "keep ≲ 0.3 for weak compressibility")
        add("time steps", f"{int(44000 * dur)}", "lattice steps")
        if tau < 0.505:
            add("⚠ τ", "very close to 0.5", "", "the BGK scheme becomes inaccurate/unstable")
    elif exhibit == "Porous Flow":
        nx, ny = int(380 * s), int(360 * s)
        grain = max(4, int(float(p["grain"]) * ny)); tau, force = 0.8, 1.2e-5
        add("grid", f"{nx} × {ny}", "cells"); add("grain radius", f"{grain}", "cells")
        add("viscosity ν", f"{(tau - 0.5) / 3:.3f}", "lattice"); add("body force density g", f"{force:.1e}", "lattice", "Stokes regime")
        add("time steps", f"{int(24000 * dur)}", "lattice steps")
    elif exhibit in ("Rising Smoke", "Candle Flame", "Mushroom Clouds", "Rayleigh-Benard", "Chimney Plume"):
        dims = {"Rising Smoke": (280, 440), "Mushroom Clouds": (280, 440), "Rayleigh-Benard": (480, 230),
                "Candle Flame": (190, 360), "Chimney Plume": (540, 420)}[exhibit]
        nx, ny = int(dims[0] * s), int(dims[1] * s)
        add("grid", f"{nx} × {ny}", "cells (dx = dt = 1)"); add("time steps", f"{int(4800 * dur)}", "steps")
        if exhibit == "Rayleigh-Benard":
            nu = float(p["viscosity"]); kap = float(p.get("kappa", 0.02)); b = float(p["buoyancy"])
            H = ny
            add("thermal diffusivity κ", f"{kap:.3g}", "grid units")
            add("Prandtl number ν/κ", _fmt_ratio(nu, kap))
            add("Rayleigh number  β·ΔT·H³/(ν κ)", _fmt_ratio(b * H ** 3, nu * kap), "",
                "β·ΔT = buoyancy coefficient, H = layer height in CELLS, so this value changes with the "
                "resolution setting (a resolution change is not a convergence study here). Onset ≈ 1708 "
                "applies to rigid no-slip conducting plates.")
    elif exhibit == "Detonation":
        nx = ny = int(420 * s); ratio = float(p["pressure"]); p_amb = 0.1
        add("grid", f"{nx} × {ny}", "cells"); add("ambient pressure", f"{p_amb}", "code")
        add("charge pressure p₀ = ratio × ambient", f"{ratio * p_amb:.3g}", "code")
        add("charge radius", f"{float(p['charge']) * nx:.0f}", "cells"); add("end time", f"{70 * dur:.0f}", "code units")
    elif exhibit == "Shock Tube":
        nx, ny = int(600 * s), 24; tend = 0.2 * nx * dur
        add("cells along the tube", f"{nx}", "", "tube length 1; the strip height is for display only")
        add("end time", f"{tend / nx:.3f}", "tube-length units", f"({tend:g} code units; reference 0.2)")
        add("expected mean density error", "≈ 0.003 at 300 cells, ≈ 0.002 at 600", "", "first order at the discontinuities")
    elif exhibit == "Shockwave Strike":
        nx, ny = int(620 * s), int(320 * s); G = 1.4; Ms = float(p["mach"])
        rr = ((G + 1) * Ms * Ms) / ((G - 1) * Ms * Ms + 2.0); pr = (2.0 * G * Ms * Ms - (G - 1)) / (G + 1)
        add("grid", f"{nx} × {ny}", "cells")
        add("post-shock density ρ₂/ρ₁", f"{rr:.3f}", "", "Rankine–Hugoniot"); add("post-shock pressure p₂/p₁", f"{pr:.3f}")
        add("Atwood number (bubble vs air)", f"{(float(p['densratio']) - 1) / (float(p['densratio']) + 1):.3f}")
    elif exhibit == "The Big Splash":
        sc = engine._SPLASH_SCENE.get(p.get("scene", "Dam break"), "dam"); Lx, Ly = engine._SPLASH_TANK[sc]
        g = float(p["gravity"]); npart = max(500.0, float(p["particles"]))
        if sc == "pour":
            H = Ly; dp = Lx / 44.0
        else:
            H = float(p["height"]) if sc == "dam" else Ly * 0.5
            dp = float(np.clip(np.sqrt(Lx * Ly * 0.4 / npart), 0.02, 0.08))
        c0 = 10.0 * (g * max(H, Ly * 0.5)) ** 0.5
        add("tank", f"{Lx} × {Ly}", "m"); add("particle spacing dp", f"{dp:.3f}", "m", "clamped to 0.02–0.08 m")
        fill = {"dam": float(p.get("width", 1.0)) * float(p.get("height", 2.0)), "drop": Lx * 0.30 * Ly,
                "slosh": Lx * 0.42 * Ly, "rest": Lx * 0.42 * Ly, "waves": Lx * 0.40 * Ly, "ship": Lx * 0.40 * Ly,
                "pour": 0.0}.get(sc, 0.0)
        add("estimated particles", f"{int(fill / dp / dp)}" if sc != "pour" else "emitted continuously (≤ 22 000)", "", "the particle count is set by dp and the water area")
        add("numerical sound speed c₀", f"{c0:.1f}", "m/s", "10 × √(g H): weakly compressible")
        add("time step", f"{0.08 * 1.3 * dp / c0:.2e}", "s")
        if sc == "pour":
            sw = max(3.0 * dp, float(p.get("spout", 0.045)) * Lx)
            add("applied spout half-width", f"{sw:.4f}", "m", "≥ 3 dp so the stream is resolved")
    elif exhibit in ("Cloud Billows", "Ink in Motion"):
        n = int(256 * s); L = 2 * math.pi; dt = 0.4 * (L / n)
        T_end = (2800 if exhibit == "Cloud Billows" else 2600) * dur * 0.4 * (L / 256)
        add("grid", f"{n} × {n}", "", "periodic box L = 2π"); add("time step", f"{dt:.4f}"); add("end time", f"{T_end:.2f}")
        add("steps", f"{max(1, int(round(T_end / dt)))}")
        if exhibit == "Cloud Billows":
            add("viscosity ν", f"{float(p['viscosity']):.2e}")
    elif exhibit == "Turing Patterns":
        from .reaction import PRESETS
        pat = p.get("pattern", "Spots")
        if pat == "Custom":
            F, k = float(p.get("F", 0.035)), float(p.get("k", 0.065))
        else:
            F, k = PRESETS.get(pat, (0.035, 0.065))
        add("grid", f"{int(220 * s)} × {int(220 * s)}"); add("feed F", f"{F:.4f}"); add("removal k", f"{k:.4f}")
        add("diffusivities Du, Dv", f"{p.get('Du', 0.16)}, {p.get('Dv', 0.08)}"); add("steps", f"{int(9000 * dur)}")
    return out
