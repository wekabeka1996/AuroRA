from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict
import math

@dataclass
class EVTFit:
    u: float
    xi: float
    beta: float
    n_exc: int
    n: int


class EVTCVaR:
    def __init__(self, min_exceedances: int = 500):
        self.min_exceedances = min_exceedances
        self._fit: EVTFit | None = None

    def fit(self, losses: List[float], u_quantile: float = 0.95) -> Dict[str, float]:
        if not losses:
            self._fit = EVTFit(u=0.0, xi=0.0, beta=0.0, n_exc=0, n=0)
            return self._fit.__dict__
        xs = sorted(losses)
        n = len(xs)
        k = max(1, int(math.floor(u_quantile * n)))
        u = xs[k - 1]
        # Excesses
        Y = [x - u for x in xs if x > u]
        n_exc = len(Y)
        if n_exc < self.min_exceedances or n_exc == 0:
            self._fit = EVTFit(u=u, xi=0.0, beta=0.0, n_exc=n_exc, n=n)
            return self._fit.__dict__
        # Simple method-of-moments for GPD as a stable baseline:
        m1 = sum(Y) / n_exc
        m2 = sum(y * y for y in Y) / n_exc
        # Start with xi from MoM and clamp to a safe range; ensure beta > 0
        if m2 <= 2 * m1 * m1:
            xi = 0.0
        else:
            xi = 0.5 * (m2 / (m1 * m1) - 1)
        # Guard xi in [0, 0.95] to avoid infinite/negative scales
        if xi < 0:
            xi = 0.0
        if xi >= 0.95:
            xi = 0.95
        beta = m1 * (1 - xi)
        # Minimal positive scale guard
        if beta <= 0:
            beta = max(1e-9, m1 * 0.05)
        self._fit = EVTFit(u=u, xi=float(xi), beta=float(beta), n_exc=n_exc, n=n)
        return self._fit.__dict__

    def cvar(self, alpha: float) -> float:
        if self._fit is None:
            return float('nan')
        u, xi, beta, n_exc, n = self._fit.u, self._fit.xi, self._fit.beta, self._fit.n_exc, self._fit.n
        if n_exc == 0:
            return float('nan')
        # Tail probability above u
        p_tail = n_exc / n
        # If alpha below u-quantile region, return u as conservative
        if alpha <= 1 - p_tail:
            return u
        # POT CVaR approx; guard xi near 1
        eps = 1e-9
        if xi >= 1 - eps:
            xi = 1 - eps
        if xi <= 0:
            # Exponential tail
            t = (1 - alpha) / p_tail
            if t <= 0:
                t = eps
            return u + beta + beta * math.log(1 / t)
        # General case
        t = ((1 - alpha) / p_tail) ** (-xi)
        return (u + (beta / (1 - xi))) * t
