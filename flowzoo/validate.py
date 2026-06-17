"""Analytical benchmarks used to validate the solvers."""
from __future__ import annotations

import numpy as np


def exact_sod(x, t, gamma=1.4, x0=0.5,
              left=(1.0, 0.0, 1.0), right=(0.125, 0.0, 0.1)):
    """Exact Riemann (Sod) solution: density at positions `x` and time `t`.

    Returns rho(x). Standard star-region pressure via Newton iteration, then
    sampling of rarefaction / contact / shock structure (Toro, Ch. 4).
    """
    rL, uL, pL = left
    rR, uR, pR = right
    aL, aR = np.sqrt(gamma * pL / rL), np.sqrt(gamma * pR / rR)
    g = gamma

    def fK(p, rK, pK, aK):
        if p > pK:  # shock
            A = 2.0 / ((g + 1) * rK); B = (g - 1) / (g + 1) * pK
            return (p - pK) * np.sqrt(A / (p + B))
        else:        # rarefaction
            return (2 * aK / (g - 1)) * ((p / pK) ** ((g - 1) / (2 * g)) - 1)

    def f(p):
        return fK(p, rL, pL, aL) + fK(p, rR, pR, aR) + (uR - uL)

    # Newton for star pressure
    p = 0.5 * (pL + pR)
    for _ in range(100):
        dp = 1e-6 * p
        fp = f(p); df = (f(p + dp) - fp) / dp
        pn = max(1e-8, p - fp / df)
        if abs(pn - p) < 1e-10 * pn:
            p = pn; break
        p = pn
    ps = p
    us = 0.5 * (uL + uR) + 0.5 * (fK(ps, rR, pR, aR) - fK(ps, rL, pL, aL))

    out = np.empty_like(np.asarray(x, dtype=float))
    for k, xi in enumerate(np.atleast_1d(x)):
        S = (xi - x0) / t
        if S <= us:  # left of contact
            if ps > pL:  # left shock
                SL = uL - aL * np.sqrt((g + 1) / (2 * g) * ps / pL + (g - 1) / (2 * g))
                out[k] = rL if S < SL else rL * (ps / pL + (g - 1) / (g + 1)) / \
                    ((g - 1) / (g + 1) * ps / pL + 1)
            else:        # left rarefaction
                rs = rL * (ps / pL) ** (1 / g)
                SHL = uL - aL; asl = aL * (ps / pL) ** ((g - 1) / (2 * g)); STL = us - asl
                if S < SHL: out[k] = rL
                elif S > STL: out[k] = rs
                else:
                    u = 2 / (g + 1) * (aL + (g - 1) / 2 * uL + S)
                    a = 2 / (g + 1) * (aL + (g - 1) / 2 * (uL - S))
                    out[k] = rL * (a / aL) ** (2 / (g - 1))
        else:        # right of contact
            if ps > pR:  # right shock
                SR = uR + aR * np.sqrt((g + 1) / (2 * g) * ps / pR + (g - 1) / (2 * g))
                out[k] = rR if S > SR else rR * (ps / pR + (g - 1) / (g + 1)) / \
                    ((g - 1) / (g + 1) * ps / pR + 1)
            else:        # right rarefaction
                rs = rR * (ps / pR) ** (1 / g)
                SHR = uR + aR; asr = aR * (ps / pR) ** ((g - 1) / (2 * g)); STR = us + asr
                if S > SHR: out[k] = rR
                elif S < STR: out[k] = rs
                else:
                    a = 2 / (g + 1) * (aR - (g - 1) / 2 * (uR - S))
                    out[k] = rR * (a / aR) ** (2 / (g - 1))
    return out
