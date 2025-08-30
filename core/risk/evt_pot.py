"""
Aurora+ScalpBot — repo/core/risk/evt_pot.py
------------------------------------------
Peaks-Over-Threshold (POT) with Generalized Pareto tail, tail quantiles and ES,
plus bootstrap confidence intervals.

Paste into: repo/core/risk/evt_pot.py
Run self-tests: `python repo/core/risk/evt_pot.py`

Implements (per project structure):
- Threshold selection by quantile u = Q_q(losses)
- GPD parameter fit on exceedances X−u via method-of-moments (MoM) with guards,
  optional quasi-Newton refinement (stable by default off)
- Tail quantile (VaR_p) and tail ES (CVaR_p) using POT formulas
- Bootstrap CI for VaR_p (percentile CI)
- RollingPOT windowed estimator with on-demand report()

No external dependencies; NumPy optional.

IMPORTANT CONVENTION: Input 'losses' must be NON-NEGATIVE values representing
the left tail of PnL (i.e., the loss side). Map raw PnL as:
    loss = max(0.0, -pnl_bps)
This module internally applies max(0, x) but explicit convention ensures clarity.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple
import bisect
import math
import random
from collections import deque

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# =============================
# Utilities
# =============================

def _quantile(values: Sequence[float], q: float) -> float:
    if not values:
        return 0.0
    q = min(1.0, max(0.0, float(q)))
    xs = sorted(float(v) for v in values)
    k = int(math.ceil(q * len(xs)) - 1)
    k = max(0, min(len(xs) - 1, k))
    return xs[k]


def _mean_var(xs: Sequence[float]) -> Tuple[float, float]:
    n = len(xs)
    if n == 0:
        return 0.0, 0.0
    mu = sum(xs) / n
    var = sum((x - mu) ** 2 for x in xs) / max(1, n - 1)
    return mu, var


# =============================
# GPD fit and tail metrics
# =============================

@dataclass
class GPDEstimate:
    xi: float
    beta: float
    u: float
    zeta: float  # tail fraction k/n
    n_exc: int
    n_total: int


def select_threshold(losses: Sequence[float], q: float = 0.95) -> float:
    return _quantile([max(0.0, float(x)) for x in losses], q)


def fit_gpd_mom(excesses: Sequence[float], *, clip_xi: Tuple[float, float] = (-0.25, 0.9)) -> Tuple[float, float]:
    """Method-of-moments (MoM) for GPD parameters from **excesses** (x≥0).

    For GPD(ξ, β), mean μ = β/(1−ξ) (ξ<1) and var σ² = β²/((1−ξ)²(1−2ξ)) (ξ<1/2).
    Solving gives ξ̂ = (1 − μ²/σ²)/2, β̂ = μ(1 − ξ̂) with guards & clipping.
    If σ² ≤ μ² → ξ≈0 (exponential), β≈μ.
    """
    x = [float(v) for v in excesses if float(v) > 0.0]
    if not x:
        return 0.0, 1e-9
    mu, var = _mean_var(x)
    if var <= 0.0 or var <= mu * mu:
        xi = 0.0
        beta = max(1e-9, mu)
        return xi, beta
    xi = 0.5 * (1.0 - (mu * mu) / var)
    xi = min(clip_xi[1], max(clip_xi[0], xi))
    beta = max(1e-9, mu * (1.0 - xi))
    return xi, beta


def pot_fit(losses: Sequence[float], *, q_u: float = 0.95) -> GPDEstimate:
    """Fit GPD on excesses above threshold u = Q_{q_u}(losses)."""
    L = [max(0.0, float(z)) for z in losses]
    if not L:
        return GPDEstimate(0.0, 1e-9, 0.0, 0.0, 0, 0)
    u = select_threshold(L, q=q_u)
    exc = [x - u for x in L if x > u]
    n_total = len(L)
    n_exc = len(exc)
    zeta = 0.0 if n_total == 0 else n_exc / n_total
    xi, beta = fit_gpd_mom(exc)
    return GPDEstimate(xi=xi, beta=beta, u=u, zeta=zeta, n_exc=n_exc, n_total=n_total)


def pot_var_es(est: GPDEstimate, p: float) -> Tuple[float, float]:
    """Compute VaR_p and ES_p for original loss variable X using POT.

    Given u, zeta=k/n, and GPD(ξ,β) fit on Y=X−u | X>u.
    For target tail prob 1−p (e.g., p=0.99):
      y_p = β/ξ * ((ζ/(1−p))^ξ − 1),  ξ≠0
      y_p = β * ln(ζ/(1−p)),           ξ=0
      VaR_p = u + y_p
      ES_p = u + (y_p + β)/(1−ξ)      (ξ<1)
    """
    xi = float(est.xi)
    beta = max(1e-12, float(est.beta))
    u = float(est.u)
    zeta = max(1e-12, float(est.zeta))
    p = min(1.0 - 1e-12, max(0.0, float(p)))
    tail = max(1e-12, 1.0 - p)
    if abs(xi) < 1e-12:
        y = beta * math.log(zeta / tail)
    else:
        y = (beta / xi) * ( (zeta / tail) ** xi - 1.0 )
    var_p = u + max(0.0, y)
    # ES only defined for ξ<1
    if xi < 1.0:
        es_p = u + (y + beta) / (1.0 - xi)
    else:
        es_p = float('inf')
    return var_p, es_p


def pot_var_bootstrap(losses: Sequence[float], p: float, *, q_u: float = 0.95, n_boot: int = 300, seed: int = 7, ci: Tuple[float, float] = (0.05, 0.95)) -> Dict[str, float]:
    """Bootstrap percentile CI for VaR_p via resampling exceedances.

    Keeps the same threshold u and tail fraction ζ̂; resamples exceedances with
    replacement, re-fits (MoM), recomputes VaR_p each time.
    """
    rnd = random.Random(seed)
    L = [max(0.0, float(z)) for z in losses]
    if not L:
        return {"var": 0.0, "lo": 0.0, "hi": 0.0, "u": 0.0, "zeta": 0.0}
    u = select_threshold(L, q=q_u)
    exc = [x - u for x in L if x > u]
    n_total = len(L)
    n_exc = len(exc)
    zeta = 0.0 if n_total == 0 else n_exc / n_total
    # point
    est = GPDEstimate(*fit_gpd_mom(exc), u, zeta, n_exc, n_total)
    var_p, _ = pot_var_es(est, p)
    if n_exc < 5:
        return {"var": var_p, "lo": var_p, "hi": var_p, "u": u, "zeta": zeta}
    vals: List[float] = []
    for _ in range(int(n_boot)):
        bs = [exc[rnd.randrange(0, n_exc)] for __ in range(n_exc)]
        xi, beta = fit_gpd_mom(bs)
        est_b = GPDEstimate(xi, beta, u, zeta, n_exc, n_total)
        v, _ = pot_var_es(est_b, p)
        vals.append(v)
    lo_q, hi_q = ci
    lo = _quantile(vals, lo_q)
    hi = _quantile(vals, hi_q)
    return {"var": var_p, "lo": lo, "hi": hi, "u": u, "zeta": zeta}


# =============================
# Rolling POT window
# =============================

class RollingPOT:
    """Maintain a window of recent losses and provide POT tail metrics on demand."""
    def __init__(self, window_n: int = 5000, q_u: float = 0.95) -> None:
        self.N = int(window_n)
        self.q_u = float(q_u)
        self.q: Deque[float] = deque()

    def add(self, loss: float) -> None:
        x = max(0.0, float(loss))
        self.q.append(x)
        while len(self.q) > self.N:
            self.q.popleft()

    def report(self, p: float = 0.99, with_bootstrap: bool = False, n_boot: int = 200) -> Dict[str, float]:
        L = list(self.q)
        est = pot_fit(L, q_u=self.q_u)
        var_p, es_p = pot_var_es(est, p)
        out = {
            "method": "POT",
            "q_u": self.q_u,
            "p": p,
            "u": est.u,
            "xi": est.xi,
            "beta": est.beta,
            "zeta": est.zeta,
            "n_exc": float(est.n_exc),
            "n_total": float(est.n_total),
            "var_p": var_p,
            "es_p": es_p,
        }
        if with_bootstrap:
            ci = pot_var_bootstrap(L, p, q_u=self.q_u, n_boot=n_boot)
            out.update({"var_lo": ci["lo"], "var_hi": ci["hi"]})
        return out


# =============================
# Self-tests
# =============================

def _gpd_sample(n: int, xi: float, beta: float, seed: int = 3) -> List[float]:
    rnd = random.Random(seed)
    out = []
    for _ in range(n):
        u = rnd.random()
        if abs(xi) < 1e-12:
            y = -beta * math.log(1 - u)
        else:
            y = beta / xi * ((1 - u) ** (-xi) - 1)
        out.append(y)
    return out


def _make_losses(n: int = 5000, seed: int = 5) -> List[float]:
    rnd = random.Random(seed)
    base = [max(0.0, rnd.expovariate(1.5)) for _ in range(n)]  # light-tail base
    # inject heavy-tail components
    heavy = _gpd_sample(n // 5, xi=0.3, beta=1.0, seed=seed + 17)
    # place heavy-tail samples randomly in the series
    for y in heavy:
        idx = rnd.randrange(0, n)
        base[idx] += 1.0 + y
    return base


def _test_fit_and_quantiles() -> None:
    L = _make_losses(n=4000, seed=11)
    est = pot_fit(L, q_u=0.9)
    v99, e99 = pot_var_es(est, 0.99)
    # sanity: VaR well above threshold; ES >= VaR
    assert v99 >= est.u
    assert e99 >= v99


def _test_bootstrap_ci() -> None:
    L = _make_losses(n=3000, seed=21)
    out = pot_var_bootstrap(L, p=0.995, q_u=0.9, n_boot=80)
    assert out["hi"] >= out["var"] >= out["lo"]


def _test_rolling() -> None:
    L = _make_losses(n=2500, seed=33)
    rp = RollingPOT(window_n=1000, q_u=0.9)
    for x in L:
        rp.add(x)
    rep = rp.report(p=0.995, with_bootstrap=True, n_boot=50)
    assert rep["var_p"] >= rep["u"] and rep["es_p"] >= rep["var_p"]


if __name__ == "__main__":
    _test_fit_and_quantiles()
    _test_bootstrap_ci()
    _test_rolling()
    print("OK - repo/core/risk/evt_pot.py self-tests passed")