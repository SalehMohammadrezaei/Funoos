"""2-D time-dependent Schrödinger equation — split-step Fourier (ħ = m = 1).

    i ∂ψ/∂t = −½ ∇²ψ + V(x,y) ψ

Each step applies a half potential kick, a full kinetic drift (diagonal in
Fourier space), then a half potential kick — second-order accurate and unitary,
so the norm is conserved to round-off (our validation). Scenes:

    free      — a Gaussian wavepacket spreading
    barrier   — quantum tunnelling through a thin wall
    slit      — the double-slit interference pattern
    harmonic  — a coherent state sloshing in a parabolic well
"""
from __future__ import annotations

import numpy as np


def simulate(n=256, scene="barrier", k0=0.0, width=0.06, v0=320.0,
             steps=360, nframes=120, L=1.0, progress=None):
    x = np.linspace(-L / 2, L / 2, n, endpoint=False)
    X, Y = np.meshgrid(x, x, indexing="ij")
    dx = L / n
    # wavevectors
    k = 2 * np.pi * np.fft.fftfreq(n, d=dx)
    KX, KY = np.meshgrid(k, k, indexing="ij")
    K2 = KX ** 2 + KY ** 2

    sig = width * L
    # initial packet + potential per scene
    if scene == "harmonic":
        omega = 38.0
        V = 0.5 * omega ** 2 * (X ** 2 + Y ** 2)
        x0, y0, kx, ky = -0.22 * L, 0.0, 0.0, 0.0
    elif scene == "barrier":
        V = np.where(np.abs(X) < 0.012 * L, v0, 0.0)
        x0, y0, kx, ky = -0.28 * L, 0.0, (k0 or 360.0), 0.0
    elif scene == "slit":
        gap = 0.045 * L; sep = 0.10 * L; thick = 0.014 * L
        wall = np.abs(X) < thick
        slits = (np.abs(Y - sep / 2) < gap / 2) | (np.abs(Y + sep / 2) < gap / 2)
        V = np.where(wall & ~slits, v0, 0.0)
        x0, y0, kx, ky = -0.30 * L, 0.0, (k0 or 360.0), 0.0
    else:  # free
        V = np.zeros((n, n))
        x0, y0, kx, ky = -0.18 * L, 0.0, (k0 or 220.0), 0.0

    psi = np.exp(-((X - x0) ** 2 + (Y - y0) ** 2) / (2 * sig ** 2)).astype(complex)
    psi *= np.exp(1j * (kx * X + ky * Y))
    psi /= np.sqrt(np.sum(np.abs(psi) ** 2) * dx * dx)

    dt = 1.0 / steps * 0.9
    expV = np.exp(-1j * V * dt / 2)
    expK = np.exp(-1j * K2 * dt / 2)
    # soft absorbing border (not for the bound harmonic well)
    if scene != "harmonic":
        r = np.maximum(np.abs(X), np.abs(Y)) / (L / 2)
        tt = np.clip((r - 0.85) / 0.15, 0.0, 1.0)        # 0 inside, 1 at the wall
        absorb = np.cos(tt * np.pi / 2) ** 0.5           # smooth taper to 0 at the edge
    else:
        absorb = None

    every = max(1, steps // nframes); pevery = max(1, steps // 50)
    prob, phase, norm = [], [], []
    n0 = np.sum(np.abs(psi) ** 2) * dx * dx
    for s in range(steps + 1):
        if s % every == 0:
            p = np.abs(psi) ** 2
            prob.append(p.copy()); phase.append(np.angle(psi))
            norm.append(float(np.sum(p) * dx * dx) / n0)
        if progress and s % pevery == 0:
            progress(s / steps)
        psi = expV * psi
        psi = np.fft.ifft2(expK * np.fft.fft2(psi))
        psi = expV * psi
        if absorb is not None:
            psi *= absorb
    return prob, phase, V, norm
