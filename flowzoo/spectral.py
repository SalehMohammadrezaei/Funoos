"""2D pseudo-spectral vorticity-streamfunction solver (FFT).

Periodic box, vorticity transport  d(omega)/dt + u.grad(omega) = nu * lap(omega).
The nonlinear term is evaluated in physical space (pseudo-spectral) with 2/3-
rule dealiasing; the viscous term is integrated exactly (integrating factor) and
the advection term with RK4. Space is spectrally accurate, but time integration is
not exact: in the inviscid limit energy is conserved only to the RK4 truncation
error (measured in tests/), not to round-off.
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

    def nonlinear(self, wh):
        """−(u·∇)ω in spectral space, dealiased (the advection term only).

        The state is truncated to the retained band before any product is formed. Masking only
        the result does not dealias: modes above the cutoff still multiply each other and land
        inside the retained band, where the mask cannot tell them from real interactions. With
        the inputs truncated, products of retained modes can only alias above the cutoff, which
        is exactly what the mask on the way out removes.
        """
        wh = wh * self.mask
        u, v = self.velocity(wh)
        wx = np.real(np.fft.ifft2(1j * self.kx * wh))
        wy = np.real(np.fft.ifft2(1j * self.ky * wh))
        return -np.fft.fft2(u * wx + v * wy) * self.mask

    def rhs(self, wh):
        return self.nonlinear(wh) - self.nu * self.k2 * wh

    def step(self, wh, dt):
        """Integrating-factor RK4: the viscous term e^{−νk²t} is applied exactly and RK4
        advances only the advection term, so there is no diffusive time-step limit
        (explicit RK4 on ν k² ω is unstable once ν k_max² dt exceeds ≈ 2.8) and the
        advection CFL alone sets dt. Fourth order in time; with ν = 0 it reduces to
        classical RK4."""
        E = np.exp(-0.5 * self.nu * self.k2 * dt); E2 = E * E
        a = self.nonlinear(wh)
        b = self.nonlinear(E * (wh + 0.5 * dt * a))
        c = self.nonlinear(E * wh + 0.5 * dt * b)
        d = self.nonlinear(E2 * wh + dt * E * c)
        # the state stays inside the retained band, so the scheme is a Galerkin truncation
        return (E2 * wh + (dt / 6.0) * (E2 * a + 2.0 * E * (b + c) + d)) * self.mask

    def energy(self, wh):
        u, v = self.velocity(wh)
        return 0.5 * np.mean(u * u + v * v)

    def vorticity(self, wh):
        return np.real(np.fft.ifft2(wh))


N_REF = 256      # reference spectral resolution of random initial conditions


def random_field(n, L=2 * np.pi, k0=14.0, seed=0, n_ref=N_REF):
    """Random vorticity with a peaked spectrum → decaying turbulence (the derived velocity is
    solenoidal). The random phases are drawn on a FIXED reference grid (n_ref × n_ref
    spectral modes) and the field is then truncated or zero-padded to the target grid, so
    the same seed gives the same continuous initial condition at every resolution (tested)."""
    rng = np.random.default_rng(seed)
    k1r = np.fft.fftfreq(n_ref, d=L / n_ref) * 2 * np.pi
    kxr = k1r[:, None]; kyr = k1r[None, :]; kr = np.sqrt(kxr ** 2 + kyr ** 2)
    amp = kr / (1.0 + (kr / k0) ** 4)
    wh_ref = amp * np.exp(1j * rng.uniform(0, 2 * np.pi, (n_ref, n_ref)))       # spectral coefficients on the reference grid
    w_ref = np.real(np.fft.ifft2(wh_ref)); w_ref -= w_ref.mean(); w_ref /= (w_ref.std() + 1e-12)
    wh_ref = np.fft.fft2(w_ref)
    wh_ref[n_ref // 2, :] = 0; wh_ref[:, n_ref // 2] = 0      # no Nyquist content: the spectrum then pads/truncates exactly
    if n == n_ref:
        return wh_ref
    return _resample_spectral(wh_ref, n)


def _resample_spectral(wh, n):
    """Truncate or zero-pad a 2-D spectrum to n × n modes (physical values preserved).
    Truncation keeps |k| < n/2 only, so the coarse field is the exact low-pass of the fine one."""
    m = wh.shape[0]; out = np.zeros((n, n), complex)
    h = min(m, n) // 2
    for sx in (slice(0, h), slice(-h, None)):
        for sy in (slice(0, h), slice(-h, None)):
            out[sx, sy] = wh[sx, sy]
    if n < m:
        out[n // 2, :] = 0; out[:, n // 2] = 0
    return out * (n * n) / (m * m)


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


def double_shear_layer(n, L=2 * np.pi, delta=1 / 30, amp=0.05):
    """Classic doubly-periodic shear-layer initial condition (rolls into billows).
    `delta` is the tanh layer thickness as a fraction of L (default L/30)."""
    x = np.linspace(0, L, n, endpoint=False)
    X, Y = np.meshgrid(x, x, indexing="ij")
    rho_w = 1.0 / (max(delta, 1e-4) * L)
    u = np.where(Y <= L / 2, np.tanh(rho_w * (Y - L / 4)),
                 np.tanh(rho_w * (3 * L / 4 - Y)))
    v = amp * np.sin(2 * np.pi * X / L)
    w = np.gradient(v, L / n, axis=0) - np.gradient(u, L / n, axis=1)
    return np.fft.fft2(w)


def taylor_green(n, L=2 * np.pi):
    """Taylor–Green vortex (wavenumber 1): ψ = sin x sin y, ω = 2 sin x sin y. An exact solution of the
    2-D Navier–Stokes equations in a 2π box, where k² = 2. The vorticity and velocity amplitudes decay
    as exp(−νk²t) = exp(−2νt); the kinetic energy is quadratic in them and so decays twice as fast,
    as exp(−4νt). The decay check in the tests measures the energy."""
    x = np.linspace(0, L, n, endpoint=False)
    X, Y = np.meshgrid(x, x, indexing="ij")
    return np.fft.fft2(2.0 * np.sin(X) * np.sin(Y))
