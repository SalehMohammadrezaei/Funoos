"""Read the C++ solver's output: meta.txt + float32 velocity frames."""
from __future__ import annotations

from pathlib import Path
import numpy as np


def read_meta(out_dir):
    meta = {}
    for line in (Path(out_dir) / "meta.txt").read_text().splitlines():
        k, v = line.split()
        meta[k] = float(v) if "." in v or "e" in v.lower() else int(v)
    return meta


def read_frame(out_dir, i, nx, ny):
    """Return (ux, uy), each (Ny, Nx)."""
    buf = np.fromfile(Path(out_dir) / f"frame_{i:05d}.bin", dtype=np.float32)
    ux = buf[: nx * ny].reshape(ny, nx)
    uy = buf[nx * ny :].reshape(ny, nx)
    return ux, uy


def read_all_frames(out_dir):
    meta = read_meta(out_dir)
    nx, ny, n = meta["nx"], meta["ny"], meta["nframes"]
    return meta, [read_frame(out_dir, i, nx, ny) for i in range(n)]
