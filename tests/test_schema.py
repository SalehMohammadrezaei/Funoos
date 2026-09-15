"""Parameter-schema tests (run with: python tests/test_schema.py).

Every shipped preset is valid; invalid values fail before any solver starts;
hidden (dependency-gated) controls are ignored; integers are coerced; soft ranges
are warnings only in advanced mode; active controls change the intended derived
quantities; the blast pressure control is a ratio converted consistently.
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import schema, engine, catalog   # noqa: E402


def test_all_presets_valid():
    assert schema.check_presets() == [], schema.check_presets()
    for s in catalog.SCENES:
        v = schema.validate(s["exhibit"], s["preset"])
        assert v.ok and not v.warnings, (s["key"], v.warnings)


def test_every_descriptor_is_complete():
    for name, spec in engine.EXHIBITS.items():
        for q in spec["params"]:
            assert q.get("type") in ("float", "int", "choice", "str"), (name, q["name"])
            assert q.get("help"), (name, q["name"], "help text")
            assert "default" in q and q.get("group") in ("Geometry", "Physics", "Render"), (name, q["name"])
            if q["type"] in ("float", "int"):
                assert q["min"] <= q["default"] <= q["max"], (name, q["name"], "default inside the recommended range")
                if "hard_min" in q:
                    assert q["hard_min"] <= q["min"], (name, q["name"])
                if "hard_max" in q:
                    assert q["hard_max"] >= q["max"], (name, q["name"])
            if q["type"] == "choice":
                assert q["default"] in q["choices"], (name, q["name"])


def test_invalid_values_rejected():
    v = schema.validate("Wind Tunnel", {"reynolds": "abc"})
    assert not v.ok and "enter a number" in v.errors[0]
    v = schema.validate("Wind Tunnel", {"reynolds": float("nan")})
    assert not v.ok
    v = schema.validate("Wind Tunnel", {"speed": 0.9})
    assert not v.ok and "solver limit" in v.errors[0]
    v = schema.validate("Wind Tunnel", {"nope": 1})
    assert not v.ok and "unknown parameter" in v.errors[0]
    v = schema.validate("Wind Tunnel", {"obstacle": "Banana"})
    assert not v.ok
    v = schema.validate("Wind Tunnel", {"obstacle": "Your text", "text": "   "})
    assert not v.ok and "text" in v.errors[0].lower()
    v = schema.validate("The Big Splash", {"gravity": "9,81"})
    assert v.ok and v.params["gravity"] == 9.81, "decimal comma accepted"


def test_soft_range_needs_advanced_mode():
    v = schema.validate("Wind Tunnel", {"reynolds": 3000})
    assert not v.ok and "advanced" in v.errors[0]
    v = schema.validate("Wind Tunnel", {"reynolds": 3000}, allow_outside=True)
    assert v.ok and v.warnings and v.params["reynolds"] == 3000


def test_hidden_controls_ignored_and_ints_coerced():
    v = schema.validate("Wind Tunnel", {"obstacle": "Your text", "text": "Hi", "size": 99.0})
    assert v.ok and v.params["size"] == 0.13, "size is not an active control for text: default kept, no error"
    v = schema.validate("The Big Splash", {"scene": "Pour into a glass", "particles": 1e9})
    assert v.ok and v.params["particles"] == 3000, "pour ignores the particle count"
    v = schema.validate("Detonation", {"debris": 12.6})
    assert v.ok and v.params["debris"] == 13 and any("rounded" in a for a in v.applied)
    v = schema.validate("Detonation", {"debris": -3})
    assert not v.ok


def test_active_controls_change_derived_quantities():
    d1 = {x["label"]: x["value"] for x in schema.derived("Wind Tunnel", {"reynolds": 100})}
    d2 = {x["label"]: x["value"] for x in schema.derived("Wind Tunnel", {"reynolds": 200})}
    assert d1["viscosity ν = (τ−½)/3"] != d2["viscosity ν = (τ−½)/3"], "Re changes ν (U, D held)"
    d3 = {x["label"]: x["value"] for x in schema.derived("Wind Tunnel", {"speed": 0.12})}
    assert d3["lattice Mach U/c_s"] != d2["lattice Mach U/c_s"]
    rb = {x["label"]: x["value"] for x in schema.derived("Rayleigh-Benard", {})}
    assert "Rayleigh number  β·ΔT·H³/(ν κ)" in rb and "Prandtl number ν/κ" in rb
    sp = {x["label"]: x["value"] for x in schema.derived("The Big Splash", {"particles": 6000})}
    sp2 = {x["label"]: x["value"] for x in schema.derived("The Big Splash", {"particles": 1000})}
    assert float(sp["particle spacing dp"]) < float(sp2["particle spacing dp"])
    pour = {x["label"]: x["value"] for x in schema.derived("The Big Splash", {"scene": "Pour into a glass", "spout": 0.005})}
    assert float(pour["applied spout half-width"]) > 0.005 * 0.13, "the applied (minimum) spout width is reported"


def test_blast_pressure_is_a_ratio():
    d = {x["label"]: x["value"] for x in schema.derived("Detonation", {"pressure": 140})}
    assert abs(float(d["charge pressure p₀ = ratio × ambient"]) - 14.0) < 1e-9
    assert catalog.scene("euler_blast")["preset"]["pressure"] == 140, "preset migrated from absolute 14 to ratio 140"


def test_run_refuses_invalid_before_solver_starts():
    import funoos_app
    from funoos_app import Api, RunStore
    called = []
    orig = engine.solve_exhibit
    engine.solve_exhibit = lambda *a, **k: called.append(1)
    try:
        api = Api(store=RunStore(max_runs=2), sweep=False)
        r = api.run("Wind Tunnel", {"reynolds": "abc"}, None, None, 26, "bad")
        assert r["ok"] is False and r["state"] == "failed" and "invalid setup" in r["error"] and not called
        assert r["validation"]["errors"]
        r2 = api.run("Wind Tunnel", {"reynolds": 3000}, None, None, 26, "soft")
        assert r2["ok"] is False and "advanced" in r2["error"] and not called
        v = api.validate("Wind Tunnel", {"reynolds": 3000}, advanced=True)
        assert v["ok"] and v["warnings"]
        d = api.derived("Porous Flow", {"porosity": 0.5})
        assert d["ok"] and d["items"]
        assert api.exhibits()["ok"] and len(api.exhibits()["exhibits"]) == len(engine.EXHIBITS)
    finally:
        engine.solve_exhibit = orig


def test_new_controls_reach_the_runners():
    """Seeds / thickness / stirring / custom F,k are honoured by the Python runners."""
    from flowzoo.spectral import double_shear_layer
    import numpy as np
    a = double_shear_layer(32, delta=1 / 30); b = double_shear_layer(32, delta=0.1)
    assert not np.allclose(a, b)
    r1 = engine.solve_exhibit("Turing Patterns", {"resolution": "Low (fast)", "duration": 0.05, "pattern": "Custom", "F": 0.02, "k": 0.05, "seed": 7})
    assert r1.hints["F"] == 0.02 and r1.hints["k"] == 0.05
    r2 = engine.solve_exhibit("Turing Patterns", {"resolution": "Low (fast)", "duration": 0.05, "pattern": "Custom", "F": 0.02, "k": 0.05, "seed": 8})
    assert not np.allclose(r1.raw[0], r2.raw[0]), "a different seed gives a different initial state"
    m = engine.solve_exhibit("Ink in Motion", {"resolution": "Low (fast)", "duration": 0.05, "stir": 0.0})
    assert m.hints["stir"] == 0.0 and np.allclose(m.raw[0].max(), 1.0)


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        t0 = time.time()
        try:
            fn(); print(f"  ok   {name}  ({time.time() - t0:.1f}s)")
        except Exception as e:                       # noqa: BLE001
            failed += 1; print(f"  FAIL {name}: {type(e).__name__}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
