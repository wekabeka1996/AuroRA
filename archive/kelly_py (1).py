"""
Aurora+ScalpBot — repo/core/sizing/kelly.py
-------------------------------------------
Kelly sizing primitives for single-asset and portfolio settings.

Paste into: repo/core/sizing/kelly.py
Run self-tests: `python repo/core/sizing/kelly.py`

Implements (per project structure):
- raw_kelly_fraction(p, G, L, f_max): f = ((b p − (1−p)) / b)_+ clipped to [0, f_max], b=G/L
- KellyOrchestrator: f* = f_raw × Π λ_i with safe clipping (λ-cal, λ-reg, λ-liq, λ-dd, λ-lat, ...)
- portfolio_kelly(mu, Sigma): w ≈ (Σ+ρI)^{-1} μ, with leverage cap and long-only option
- SPD solver fallback (Conjugate Gradient) when NumPy is unavailable

No external dependencies; NumPy optional. Fully standalone (no imports from other modules).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple
import math

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore


# =============================
# Single-asset Kelly
# =============================

def raw_kelly_fraction(p: float, G: float, L: float, f_max: float = 1.0) -> float:
    """Raw Kelly fraction for a binary trade with success prob p, gain G, loss L.

    b = G/L (odds). f = ((b p − (1−p))/b) clipped to [0, f_max].
    If inputs are invalid (p∉[0,1] or L≤0 or G≤0), returns 0.0 as a guard.
    """
    try:
        p = float(p)
        G = float(G)
        L = float(L)
        f_max = float(f_max)
    except Exception:
        return 0.0
    if not (0.0 <= p <= 1.0) or G <= 0.0 or L <= 0.0 or f_max <= 0.0:
        return 0.0
    b = G / L
    f = (b * p - (1.0 - p)) / b
    # clip
    if f < 0.0:
        return 0.0
    if f > f_max:
        return f_max
    if math.isnan(f) or math.isinf(f):
        return 0.0
    return f


# =============================
# Lambda-orchestrated Kelly
# =============================

@dataclass
class KellyOrchestrator:
    """Orchestrates raw Kelly with multiplicative λ-multipliers.

    Typical λ: cal, reg, liq, dd, lat (each in [0,1]). Missing keys default to 1.
    `cap` is the final hard cap on f* after applying multipliers.
    """
    cap: float = 1.0

    def lambda_product(self, lambdas: Optional[Mapping[str, float]]) -> float:
        if not lambdas:
            return 1.0
        prod = 1.0
        for k, v in lambdas.items():
            try:
                x = float(v)
            except Exception:
                x = 1.0
            # clip to [0,1]
            if not (0.0 <= x <= 1.0):
                x = max(0.0, min(1.0, x))
            prod *= x
        return max(0.0, min(1.0, prod))

    def size(self, p: float, G: float, L: float, *, lambdas: Optional[Mapping[str, float]] = None, f_max: Optional[float] = None) -> float:
        f_raw = raw_kelly_fraction(p, G, L, f_max=self.cap if f_max is None else min(self.cap, float(f_max)))
        mult = self.lambda_product(lambdas)
        f_star = f_raw * mult
        return max(0.0, min(self.cap, f_star))


# =============================
# Portfolio Kelly (log-utility approximation)
# =============================

def _dot(a: Sequence[float], b: Sequence[float]) -> float:
    return sum(float(x) * float(y) for x, y in zip(a, b))

def _matvec(A: Sequence[Sequence[float]], x: Sequence[float]) -> List[float]:
    return [sum(float(aij) * float(xj) for aij, xj in zip(ai, x)) for ai in A]


def _cg_spd(A: Sequence[Sequence[float]], b: Sequence[float], tol: float = 1e-9, max_iter: int = 2000) -> List[float]:
    """Conjugate Gradient for symmetric positive definite A (NumPy-free)."""
    n = len(b)
    x = [0.0] * n
    r = [bi - yi for bi, yi in zip(b, _matvec(A, x))]
    p = list(r)
    rsold = _dot(r, r)
    if rsold == 0:
        return x
    for _ in range(max_iter):
        Ap = _matvec(A, p)
        alpha = rsold / max(1e-18, _dot(p, Ap))
        x = [xi + alpha * pi for xi, pi in zip(x, p)]
        r = [ri - alpha * api for ri, api in zip(r, Ap)]
        rsnew = _dot(r, r)
        if rsnew < tol:
            break
        beta = rsnew / max(1e-18, rsold)
        p = [ri + beta * pi for ri, pi in zip(r, p)]
        rsold = rsnew
    return x


def _ridge_eye(n: int, rho: float) -> List[List[float]]:
    return [[(rho if i == j else 0.0) for j in range(n)] for i in range(n)]


def portfolio_kelly(
    mu: Sequence[float],
    Sigma: Sequence[Sequence[float]],
    *,
    ridge: float = 1e-6,
    leverage_cap: float = 1.0,
    long_only: bool = False,
) -> List[float]:
    """Approximate portfolio Kelly weights via w ≈ (Σ + ρI)^{-1} μ.

    - `mu`: expected excess returns per asset (can be per-trade bps or daily fractions)
    - `Sigma`: covariance matrix (consistent units)
    - `ridge`: small diagonal loading for numerical stability
    - `leverage_cap`: L1 cap ∑|w_i| ≤ cap (scaled if exceeded)
    - `long_only`: if True, negatives are projected to 0 with active-set refinement
    """
    n = len(mu)
    mu_v = [float(x) for x in mu]
    # Build A = Sigma + ridge * I
    if np is not None:
        A = np.array(Sigma, dtype=float)
        A = A + np.eye(n) * float(ridge)
        b = np.array(mu_v, dtype=float)
        try:
            w = np.linalg.solve(A, b)
        except Exception:
            w = np.linalg.pinv(A).dot(b)
        w_list = [float(x) for x in w.tolist()]
    else:
        # Python fallback
        A = [[float(x) for x in row] for row in Sigma]
        rid = _ridge_eye(n, float(ridge))
        A = [[aij + rij for aij, rij in zip(arow, rrow)] for arow, rrow in zip(A, rid)]
        w_list = _cg_spd(A, mu_v, tol=1e-10, max_iter=2000)

    # Long-only projection with simple active-set refinement
    if long_only:
        active = [i for i, wi in enumerate(w_list) if wi > 0.0]
        for _ in range(5):  # a few refinements
            if not active:
                w_list = [0.0] * n
                break
            # solve on active set only
            mu_a = [mu_v[i] for i in active]
            Sig_a = [[float(Sigma[i][j]) for j in active] for i in active]
            if np is not None:
                A = np.array(Sig_a, dtype=float) + np.eye(len(active)) * float(ridge)
                b = np.array(mu_a, dtype=float)
                sol = np.linalg.pinv(A).dot(b)
                w_a = [max(0.0, float(x)) for x in sol.tolist()]
            else:
                A = [[float(x) for x in row] for row in Sig_a]
                rid = _ridge_eye(len(active), float(ridge))
                A = [[aij + rij for aij, rij in zip(arow, rrow)] for arow, rrow in zip(A, rid)]
                sol = _cg_spd(A, mu_a, tol=1e-10, max_iter=2000)
                w_a = [max(0.0, float(x)) for x in sol]
            # write back and prune negatives
            w_new = [0.0] * n
            for idx, wi in zip(active, w_a):
                w_new[idx] = wi
            w_list = w_new
            active = [i for i, wi in enumerate(w_list) if wi > 1e-15]

    # Leverage scaling
    lev = sum(abs(wi) for wi in w_list)
    cap = max(1e-12, float(leverage_cap))
    if lev > cap:
        scale = cap / lev
        w_list = [wi * scale for wi in w_list]
    return w_list


# =============================
# Self-tests
# =============================

def _test_raw_kelly() -> None:
    # b=G/L=2, p=0.6 → f=(2*0.6 − 0.4)/2 = 0.4; cap to 0.25
    f = raw_kelly_fraction(0.6, 2.0, 1.0, f_max=0.25)
    assert abs(f - 0.25) < 1e-12


def _test_portfolio_basic() -> None:
    # two assets with different risk; expect positive weights and leverage within cap
    mu = [0.01, 0.02]
    Sigma = [[0.04, 0.0], [0.0, 0.09]]
    w = portfolio_kelly(mu, Sigma, ridge=1e-8, leverage_cap=1.0, long_only=True)
    assert all(wi >= -1e-12 for wi in w)
    assert sum(abs(wi) for wi in w) <= 1.0 + 1e-9
    # asset 1 not necessarily larger; depends on μ/σ² ratio; check consistency
    assert abs(w[0] - 0.25) < 0.05 and abs(w[1] - (0.02/0.09)) < 0.05


def _test_orchestrator() -> None:
    ko = KellyOrchestrator(cap=0.5)
    f = ko.size(0.58, 1.5, 1.0, lambdas={"cal": 0.9, "reg": 0.8})
    assert 0.0 <= f <= 0.5
    # if λ→0, size→0
    f0 = ko.size(0.9, 2.0, 1.0, lambdas={"cal": 0.0})
    assert abs(f0) < 1e-12


if __name__ == "__main__":
    _test_raw_kelly()
    _test_portfolio_basic()
    _test_orchestrator()
    print("OK - repo/core/sizing/kelly.py self-tests passed")
