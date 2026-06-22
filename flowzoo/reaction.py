"""Gray–Scott reaction–diffusion — Turing patterns.

Two chemicals U, V diffuse and react:  U + 2V → 3V,  V → P.

    ∂U/∂t = Du ∇²U − U V² + F(1 − U)
    ∂V/∂t = Dv ∇²V + U V² − (F + k) V

A handful of (F, k) pairs select the whole zoo of self-organising patterns
Pearson classified — spots, stripes, mazes, self-replicating "mitosis" — from a
nearly uniform start. Periodic box, 9-point isotropic Laplacian, explicit Euler.
"""
from __future__ import annotations

import numpy as np

# Pearson-classified presets (Du=0.16, Dv=0.08, dt=1)
PRESETS = {
    "Spots":   (0.0300, 0.0620),
    "Stripes": (0.0545, 0.0620),
    "Maze":    (0.0290, 0.0570),
    "Mitosis": (0.0367, 0.0649),
    "Coral":   (0.0545, 0.0620),
    "Waves":   (0.0140, 0.0500),
}


def _lap(a):
    # 9-point isotropic Laplacian, periodic
    return (-a
            + 0.20 * (np.roll(a, 1, 0) + np.roll(a, -1, 0) + np.roll(a, 1, 1) + np.roll(a, -1, 1))
            + 0.05 * (np.roll(np.roll(a, 1, 0), 1, 1) + np.roll(np.roll(a, 1, 0), -1, 1)
                      + np.roll(np.roll(a, -1, 0), 1, 1) + np.roll(np.roll(a, -1, 0), -1, 1)))


def gray_scott(n=256, F=0.035, k=0.065, Du=0.16, Dv=0.08, steps=10000,
               nframes=120, seed=0):
    rng = np.random.default_rng(seed)
    U = np.ones((n, n)); V = np.zeros((n, n))
    # seed a few noisy blobs of V
    for _ in range(rng.integers(8, 16)):
        cx, cy = rng.integers(0, n, 2); r = rng.integers(6, 14)
        y, x = np.ogrid[:n, :n]
        m = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        U[m] = 0.50; V[m] = 0.25
    U += 0.02 * rng.standard_normal((n, n)); V += 0.02 * rng.standard_normal((n, n))
    U = np.clip(U, 0, 1); V = np.clip(V, 0, 1)
    every = max(1, steps // nframes)
    frames = []
    for s in range(steps + 1):
        uvv = U * V * V
        U += Du * _lap(U) - uvv + F * (1.0 - U)
        V += Dv * _lap(V) + uvv - (F + k) * V
        np.clip(U, 0, 1, out=U); np.clip(V, 0, 1, out=V)
        if s % every == 0:
            frames.append(V.copy())
    return frames
