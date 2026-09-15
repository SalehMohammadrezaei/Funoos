"""Read the C++ solvers' output: meta.txt, float32 frames (scalar or velocity), frame times."""
from __future__ import annotations

from pathlib import Path
import numpy as np


def read_meta(out_dir):
    """meta.txt as {key: number}; non-numeric values are kept as strings."""
    meta = {}
    for line in (Path(out_dir) / "meta.txt").read_text().splitlines():
        parts = line.split()
        if len(parts) != 2:
            continue
        k, v = parts
        try:
            meta[k] = int(v) if v.lstrip("-").isdigit() else float(v)
        except ValueError:
            meta[k] = v
    return meta


def read_frame(out_dir, i, nx, ny, prefix="frame"):
    """(ux, uy), each (ny, nx) float32, from <prefix>_NNNNN.bin (ux block then uy block).
    Raises ValueError on a truncated file instead of reshaping garbage."""
    buf = np.fromfile(Path(out_dir) / f"{prefix}_{i:05d}.bin", dtype=np.float32)
    if buf.size < 2 * nx * ny:
        raise ValueError(f"{prefix}_{i:05d}.bin is truncated: {buf.size} floats, expected {2 * nx * ny}")
    ux = buf[: nx * ny].reshape(ny, nx).copy()
    uy = buf[nx * ny: 2 * nx * ny].reshape(ny, nx).copy()
    return ux, uy


def read_scalar(out_dir, i, nx, ny, prefix="frame"):
    buf = np.fromfile(Path(out_dir) / f"{prefix}_{i:05d}.bin", dtype=np.float32)
    if buf.size < nx * ny:
        raise ValueError(f"{prefix}_{i:05d}.bin is truncated: {buf.size} floats, expected {nx * ny}")
    return buf[: nx * ny].reshape(ny, nx).copy()


def read_frame_times(out_dir):
    p = Path(out_dir) / "frame_times.txt"
    return [float(x) for x in p.read_text().split()] if p.exists() else []


def read_all_frames(out_dir):
    meta = read_meta(out_dir)
    nx, ny, n = int(meta["nx"]), int(meta["ny"]), int(meta["nframes"])
    return meta, [read_frame(out_dir, i, nx, ny) for i in range(n)]
