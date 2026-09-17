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
    "Stripes": (0.0220, 0.0510),
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
               nframes=120, seed=0, progress=None, nseeds=None, noise=0.02):
    """Gray–Scott on an n×n periodic grid. `nseeds` blobs of V (default: 8–15, from the
    seed) plus Gaussian `noise` start the pattern; nseeds=0 and noise=0 give the uniform
    state (U=1, V=0), which is a fixed point. U and V are clipped to [0, 1] every step —
    a numerical intervention, reported in the scene notes.

    Returns (frames, times): the state at t = 0 before anything is done to it, then the state
    after every `steps // nframes` updates and at the final step, each with the step it was
    reached at."""
    rng = np.random.default_rng(seed)
    U = np.ones((n, n)); V = np.zeros((n, n))
    nb = int(rng.integers(8, 16)) if nseeds is None else int(nseeds)
    # blob centres and radii are drawn as FRACTIONS of the box (reference grid 220), so the same
    # seed places the same blobs at every resolution
    for _ in range(nb):
        fx, fy = rng.uniform(0, 1, 2); fr = rng.uniform(6 / 220, 14 / 220)
        cx, cy, r = fx * n, fy * n, fr * n
        y, x = np.ogrid[:n, :n]
        m = (x - cx) ** 2 + (y - cy) ** 2 <= r * r
        U[m] = 0.50; V[m] = 0.25
    if noise:                                       # grid-scale noise cannot be resolution-independent; it is small
        U += noise * rng.standard_normal((n, n)); V += noise * rng.standard_normal((n, n))
    U = np.clip(U, 0, 1); V = np.clip(V, 0, 1)
    every = max(1, steps // nframes); pevery = max(1, steps // 50)
    # The initial state is a state: it is recorded before anything is done to it, and every later
    # frame is recorded after the update that produced it, at the step it reached. Updating before
    # the first save made the frame labelled t = 0 already one step old, the loop ran one update
    # more than asked, and the final state was kept only when it happened to land on the interval.
    frames = [V.copy()]; times = [0.0]
    for s in range(1, steps + 1):
        uvv = U * V * V
        U += Du * _lap(U) - uvv + F * (1.0 - U)
        V += Dv * _lap(V) + uvv - (F + k) * V
        np.clip(U, 0, 1, out=U); np.clip(V, 0, 1, out=V)
        if s % every == 0 or s == steps:
            frames.append(V.copy()); times.append(float(s))
        if progress and s % pevery == 0:
            progress(s / steps)
    return frames, times
