"""Tail metrics utilities: Hill estimator, extremal index (runs), upper tail dependence.

Design goals:
- Pure functions, vectorized with NumPy / torch optional.
- Deterministic for a given input (no random sampling inside).
- Small sample corrections where standard.

Functions:
    hill_tail_index(x, k=None, min_k=5, max_frac=0.25)
    extremal_index_runs(x, threshold_q=0.95)
    upper_tail_dependence(x, y, threshold_q=0.95)

All functions return np.nan when insufficient data.
"""
from __future__ import annotations
import numpy as np
from dataclasses import dataclass
from typing import Tuple


class InsufficientTailSamples(Exception):
    """Raised when the tail sample size chosen for Hill estimator is below required minimum."""

@dataclass
class HillResult:
    xi: float  # tail index estimate
    k: int     # number of upper order stats used


def hill_tail_index(x: np.ndarray, k: int | None = None, min_k: int = 5, max_frac: float = 0.25) -> HillResult:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < min_k + 2:
        return HillResult(np.nan, 0)
    x_sorted = np.sort(x)
    if k is None:
        k_max = int(max_frac * n)
        k_max = max(k_max, min_k)
        # Simple stability heuristic: choose k maximizing local R^2 of log-spacings linear fit
        log_tail = np.log(x_sorted[-k_max:])
        spacings = log_tail[-1] - log_tail[:-1]
        # cumulative mean of spacings -> candidate xi(k)
        cumsum = np.cumsum(spacings[::-1])[::-1]
        ks = np.arange(1, spacings.size + 1)
        xi_seq = cumsum / ks
        # pick k where xi_seq is most stable over a small window (min variance of last 5 values)
        window = 5
        if xi_seq.size < window:
            k_opt = min_k
        else:
            variances = [np.var(xi_seq[i:i+window]) for i in range(0, xi_seq.size - window + 1)]
            k_opt = ks[np.argmin(variances)]
            k_opt = int(np.clip(k_opt, min_k, k_max))
    else:
        k_opt = int(k)
    if k_opt <= 0 or k_opt >= n:
        return HillResult(np.nan, k_opt)
    # Enforce stronger minimum for production diagnostics (>=30) independent of caller min_k
    if k_opt < 30:
        raise InsufficientTailSamples(f"Chosen tail size k={k_opt} < 30 (n={n}).")
    tail = x_sorted[-k_opt:]
    xm = tail[0]
    # Hill estimator for xi (Pareto tail index)
    xi = np.mean(np.log(tail / xm + 1e-15))
    return HillResult(float(xi), k_opt)


def extremal_index_runs(x: np.ndarray, threshold_q: float = 0.95) -> float:
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = x.size
    if n < 10:
        return np.nan
    u = np.quantile(x, threshold_q)
    exceed = (x > u).astype(int)
    if exceed.sum() == 0:
        return np.nan
    # Runs estimator: theta = number of clusters / number of exceedances
    clusters = 0
    in_cluster = False
    for v in exceed:
        if v == 1 and not in_cluster:
            clusters += 1
            in_cluster = True
        elif v == 0:
            in_cluster = False
    theta = clusters / exceed.sum()
    return float(theta)


def upper_tail_dependence(x: np.ndarray, y: np.ndarray, threshold_q: float = 0.95) -> float:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    mask = ~np.isnan(x) & ~np.isnan(y)
    x = x[mask]
    y = y[mask]
    n = x.size
    if n < 20:
        return np.nan
    ux = np.quantile(x, threshold_q)
    uy = np.quantile(y, threshold_q)
    Ex = x > ux
    Ey = y > uy
    denom = Ex.sum()
    if denom == 0:
        return np.nan
    joint = (Ex & Ey).sum()
    lam_u = joint / denom
    return float(lam_u)

__all__ = [
    'hill_tail_index','extremal_index_runs','upper_tail_dependence','HillResult','InsufficientTailSamples'
]
