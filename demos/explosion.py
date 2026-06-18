"""Exhibit: explosion / blast wave with debris (compressible Euler).

A high-pressure region bursts into ambient gas — an expanding shock (schlieren)
with glowing debris flung radially outward. Thin wrapper over the shared engine
so it matches the Studio app exactly.

    python demos/explosion.py            # full quality
    python demos/explosion.py --quick
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from flowzoo import engine, render


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    args = ap.parse_args()
    params = {"resolution": "Low (fast)" if args.quick else "High", "debris": 220}
    frames, info = engine.run_exhibit("Detonation", params, print)
    render.save_gif(frames, ROOT / "results" / "explosion.gif", fps=26)
    render.save_mp4(frames, ROOT / "results" / "explosion.mp4", fps=26)
    print(f"wrote results/explosion.gif ({len(frames)} frames) — {info}")


if __name__ == "__main__":
    main()
