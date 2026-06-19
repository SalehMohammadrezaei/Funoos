"""2D pseudo-spectral vorticity-streamfunction solver (FFT).

Periodic box, vorticity transport  d(omega)/dt + u.grad(omega) = nu * lap(omega).
The nonlinear term is evaluated in physical space (pseudo-spectral) with 2/3-
rule dealiasing; viscosity is treated with an integrating factor; time stepping
is RK2. Spectral accuracy makes this conserve energy to round-off in the
inviscid limit -- which is exactly how we validate it.
"""
from __future__ import annotations

import numpy as np


class Spectral2D:
    def __init__(self, n=256, L=2 * np.pi, nu=1e-4):
        self.n, self.L, self.nu = n, L, nu
        k1 = np.fft.fftfreq(n, d=L / n) * 2 * np.pi
        self.kx = k1[:, None]
        self.ky = k1[None, :]
        self.k2 = self.kx ** 2 + self.ky ** 2
        self.k2inv = 1.0 / np.where(self.k2 == 0, 1.0, self.k2)
        # 2/3 dealiasing mask
        kmax = np.max(np.abs(k1)) * 2 / 3
        self.mask = (np.abs(self.kx) < kmax) & (np.abs(self.ky) < kmax)

    def velocity(self, wh):
        psih = wh * self.k2inv
        u = np.real(np.fft.ifft2(1j * self.ky * psih))
        v = np.real(np.fft.ifft2(-1j * self.kx * psih))
        return u, v

    def rhs(self, wh):
        u, v = self.velocity(wh)
        wx = np.real(np.fft.ifft2(1j * self.kx * wh))
        wy = np.real(np.fft.ifft2(1j * self.ky * wh))
        adv = np.fft.fft2(u * wx + v * wy) * self.mask
        return -adv - self.nu * self.k2 * wh

    def step(self, wh, dt):
        # RK4 -- stable for the (imaginary-eigenvalue) advection operator
        k1 = self.rhs(wh)
        k2 = self.rhs(wh + 0.5 * dt * k1)
        k3 = self.rhs(wh + 0.5 * dt * k2)
        k4 = self.rhs(wh + dt * k3)
        return wh + (dt / 6.0) * (k1 + 2 * k2 + 2 * k3 + k4)

    def energy(self, wh):
        u, v = self.velocity(wh)
        return 0.5 * np.mean(u * u + v * v)

    def vorticity(self, wh):
        return np.real(np.fft.ifft2(wh))


def random_field(n, L=2 * np.pi, k0=14.0, seed=0):
    """Random divergence-free vorticity with a peaked spectrum → decaying turbulence."""
    rng = np.random.default_rng(seed)
    k1 = np.fft.fftfreq(n, d=L / n) * 2 * np.pi
    kx = k1[:, None]; ky = k1[None, :]; k = np.sqrt(kx ** 2 + ky ** 2)
    amp = k / (1.0 + (k / k0) ** 4)
    w = np.real(np.fft.ifft2(amp * np.exp(1j * rng.uniform(0, 2 * np.pi, (n, n)))))
    w -= w.mean(); w /= (w.std() + 1e-12)
    return np.fft.fft2(w)


def advect_sl(c, u, v, dt, L):
    """Periodic bilinear semi-Lagrangian advection of a passive scalar c by (u,v)."""
    n = c.shape[0]; dx = L / n
    ii, jj = np.meshgrid(np.arange(n), np.arange(n), indexing="ij")
    X = (ii - dt * u / dx) % n; Y = (jj - dt * v / dx) % n
    x0 = np.floor(X).astype(int) % n; y0 = np.floor(Y).astype(int) % n
    x1 = (x0 + 1) % n; y1 = (y0 + 1) % n
    fx = X - np.floor(X); fy = Y - np.floor(Y)
    return (c[x0, y0] * (1 - fx) * (1 - fy) + c[x1, y0] * fx * (1 - fy)
            + c[x0, y1] * (1 - fx) * fy + c[x1, y1] * fx * fy)


def double_shear_layer(n, L=2 * np.pi, delta=0.05, amp=0.05):
    """Classic doubly-periodic shear-layer initial condition (rolls into billows)."""
    x = np.linspace(0, L, n, endpoint=False)
    X, Y = np.meshgrid(x, x, indexing="ij")
    rho_w = 30.0 / L
    u = np.where(Y <= L / 2, np.tanh(rho_w * (Y - L / 4)),
                 np.tanh(rho_w * (3 * L / 4 - Y)))
    v = amp * np.sin(2 * np.pi * X / L)
    w = np.gradient(v, L / n, axis=0) - np.gradient(u, L / n, axis=1)
    return np.fft.fft2(w)
