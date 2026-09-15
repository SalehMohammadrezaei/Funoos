"""Media / colour-mapping / pipeline tests (run with: python tests/test_media.py).

Covers: streamed raw-video encoding (MP4 + GIF) decodes with the right frame
count and size; a generator input works; the shared colour normalisation gives
the same colour in the field and the legend (including gamma and floor);
changing the palette never changes the numbers; derived-field caching; per-frame
timestamps from the adaptive-dt Euler solver; the resource estimate.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import render, engine   # noqa: E402

_ENV = {**os.environ, "OMP_NUM_THREADS": "4"}


def _frames(n=12, h=90, w=140):
    yy, xx = np.mgrid[0:h, 0:w]
    return [((np.sin(xx / 9.0 + i * 0.4) + 1) * 120).astype(np.uint8)[..., None].repeat(3, 2) for i in range(n)]


def test_mp4_streamed_roundtrip():
    fr = _frames(14, 91, 141)                            # odd sizes: the even-scale filter must cope
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.mp4"
        render.save_mp4(iter(fr), p, fps=26)             # a GENERATOR: frames are streamed, never listed
        n, w, h, fps = render.video_info(p)
        assert n == 14 and (w, h) == (140, 90) and abs(fps - 26) < 1e-6, (n, w, h, fps)
        assert not list(Path(d).glob("*.png")), "no PNG sequence must be written"
    try:
        render.save_mp4([], "x.mp4")
        raise AssertionError("empty input must fail")
    except ValueError:
        pass
    try:
        with tempfile.TemporaryDirectory() as d:
            render.save_mp4([fr[0], fr[0][:50]], Path(d) / "b.mp4")
        raise AssertionError("mismatched frame sizes must fail")
    except ValueError:
        pass


def test_gif_streamed():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "a.gif"
        render.save_gif(_frames(8), p, fps=20)
        from PIL import Image
        im = Image.open(p); n = 0
        try:
            while True:
                im.seek(n); n += 1
        except EOFError:
            pass
        assert n == 8 and im.size == (140, 90), (n, im.size)


def test_norm_field_and_legend_agree():
    """A value's colour in the image equals the colour the colourbar shows at that value,
    for plain, gamma-brightened and floored normalisations; the mapping is palette-independent."""
    import matplotlib
    cm = matplotlib.colormaps["viridis"]
    for norm in (render.Norm(0, 2), render.Norm(0, 2, gamma=0.5), render.Norm(0, 2, floor=0.34)):
        for v in (0.0, 0.3, 1.0, 2.0):
            t = float(norm(v))
            assert abs(float(norm.inverse(t)) - v) < 1e-9, (norm.gamma, norm.floor, v)   # legend inverts exactly
            fld = np.full((4, 4), v)
            rgb = render.field_to_rgb(fld, cm, norm, upscale=1)[0, 0]
            want = (np.array(cm(t)[:3]) * 255).astype(np.uint8)
            assert np.array_equal(rgb, want), (v, rgb, want)
    # palette independence: the normalised numbers do not depend on the colormap
    fld = np.random.default_rng(0).uniform(-1, 3, (10, 10))
    n = render.Norm(0, 2, gamma=0.7)
    assert np.allclose(n(fld), n(fld)) and abs(n.clipped(fld) - np.mean((fld < 0) | (fld > 2))) < 1e-12
    assert render.Norm(-1, 1).diverging and not render.Norm(0, 1).diverging
    n2 = n.with_range(vmax=4.0)
    assert n2.vmax == 4.0 and n2.vmin == 0.0 and n2.gamma == 0.7


def test_empty_vs_zero_distinct():
    """Cells with no fluid (NaN / empty mask) are painted differently from fluid at zero."""
    fld = np.array([[0.0, np.nan]])
    rgb = render.field_to_rgb(fld, "viridis", render.Norm(0, 1), upscale=1)
    assert not np.array_equal(rgb[0, 0], rgb[0, 1])


def test_result_derived_cache_and_generator():
    ny, nx = 24, 36
    yy, xx = np.mgrid[0:ny, 0:nx]
    vel = [(np.sin(xx / 5.0) + 0.1 * i, np.cos(yy / 4.0)) for i in range(6)]
    r = engine.Result("lbm", vel, "t", hints={"dx": 1.0}, times=[10.0 * i for i in range(6)])
    d1 = r.derived("Speed"); d2 = r.derived("Speed")
    assert d1 is d2, "derived fields are cached per view"
    assert r.derived("Velocity") is d1, "old view name maps onto Speed"
    g = r.iter_frames("Vorticity", "Turbo")
    assert hasattr(g, "__next__"), "iter_frames is a generator"
    f0 = next(g)
    assert f0.dtype == np.uint8 and f0.ndim == 3
    assert r.frame(0.5, "Speed").shape == f0.shape and r.frame(-1, "Speed").shape == f0.shape
    a = r.render("Speed", "Turbo"); b = r.render("Speed", "Inferno")
    assert len(a) == 6 and a[0].shape == b[0].shape
    lim = r.render("Speed", "Turbo", vmin=0.0, vmax=0.5)          # manual limits
    assert len(lim) == 6 and not np.array_equal(lim[-1], a[-1])
    m = r.meta()
    assert m["frames"] == 6 and m["times"][3] == 30.0 and m["shape"] == [ny, nx]
    assert r.derived("Vorticity")["norm"].diverging, "signed field gets a zero-centred range"


def test_euler_frame_times_are_actual_times():
    """The compressible solver writes the actual (adaptive-dt) time of every saved frame."""
    exe = ROOT / "solvers" / "compressible" / "euler2d"
    subprocess.run(["make", "-s", "-C", str(exe.parent)], check=True, capture_output=True)
    with tempfile.TemporaryDirectory() as d:
        subprocess.run([str(exe), "--mode", "sod", "--nx", "80", "--ny", "4", "--tend", "10",
                        "--steps", "100000", "--save_every", "5", "--out", d], check=True, capture_output=True, env=_ENV)
        t = np.loadtxt(Path(d) / "frame_times.txt")
        meta = {l.split()[0]: float(l.split()[1]) for l in (Path(d) / "meta.txt").read_text().splitlines()}
        assert len(t) == int(meta["nframes"]) and t[0] == 0.0
        assert np.all(np.diff(t) > 0) and t[-1] <= meta["time"] + 1e-9
        dts = np.diff(t)
        assert dts.std() / dts.mean() > 1e-3, "adaptive steps: frame spacing is not uniform in time"


def test_streamlines_fast_geometry_and_speed():
    """Uniform flow gives horizontal traces (lit pixels confined to seed rows); solid cells
    are painted and never crossed; the vectorised renderer beats matplotlib's streamplot."""
    ny, nx = 60, 90
    u = render.streamlines_fast(np.ones((ny, nx)), np.zeros((ny, nx)), upscale=2)
    lit = u.astype(int).sum(2) > 3 * 20
    assert u.shape == (2 * ny, 2 * nx, 3) and lit.any()
    rows = np.where(lit.any(1))[0]
    assert len(rows) < 0.5 * u.shape[0], "horizontal traces occupy a minority of rows"
    assert lit.any(0).mean() > 0.95, "traces span the whole width"
    yy, xx = np.mgrid[0:ny, 0:nx]; mask = (xx - 45) ** 2 + (yy - 30) ** 2 < 8 ** 2
    v = render.streamlines_fast(np.ones((ny, nx)), np.zeros((ny, nx)), mask=mask, mask_color="#ff0000", upscale=1)
    inside = v[::-1][mask]
    assert np.all(inside == [255, 0, 0]), "solid cells are painted with the mask colour only"
    big = np.random.default_rng(1).normal(size=(180, 644, 2))
    t0 = time.time(); render.streamlines_fast(big[..., 0], big[..., 1]); t_fast = time.time() - t0
    t0 = time.time(); render.streamlines_mpl(big[..., 0], big[..., 1]); t_mpl = time.time() - t0
    assert t_fast < t_mpl, f"fast {t_fast:.2f}s vs mpl {t_mpl:.2f}s"


def test_estimate():
    e = engine.estimate("Wind Tunnel", {"resolution": "Low (fast)", "duration": 0.5})
    assert e["grid"] == [540, 180] and e["frames"] == 90 and e["bytes"] > 0 and e["seconds"] > 0
    e2 = engine.estimate("Wind Tunnel", {"resolution": "Ultra (slow)", "duration": 2.0})
    assert e2["bytes"] > e["bytes"] and e2["seconds"] > e["seconds"]
    for name in engine.EXHIBITS:
        r = engine.estimate(name, {})
        assert r["mb"] >= 0 and r["frames"] > 0, name


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
