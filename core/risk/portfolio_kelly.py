from __future__ import annotations
import numpy as np
from typing import Tuple, List


def ledoit_wolf_shrink(S: np.ndarray) -> Tuple[np.ndarray, float]:
    """Heuristic Ledoit–Wolf-style shrinkage towards μ·I given only cov S.

    Σ̂ = (1−δ)·S + δ·μ·I, where μ = mean(diag(S)), δ∈[0,1].
    We estimate δ using the ratio of off-diagonal energy vs total deviation from μ·I.
    This keeps Σ̂ PSD as a convex combination of PSD S and μ·I.
    """
    S = np.asarray(S, dtype=float)
    # Symmetrize for numerical stability
    S = 0.5 * (S + S.T)
    n = S.shape[0]
    if n == 0:
        return S, 0.0
    mu = float(np.trace(S) / n)
    I = np.eye(n, dtype=float)
    D = S - mu * I
    # Energy split: off-diagonal vs total
    off = D.copy()
    np.fill_diagonal(off, 0.0)
    off_energy = float(np.sum(off * off))
    total_energy = float(np.sum(D * D)) + 1e-18
    delta = off_energy / total_energy
    # Clamp
    if delta < 0.0:
        delta = 0.0
    if delta > 0.95:
        delta = 0.95
    S_hat = (1.0 - delta) * S + delta * mu * I
    # Final symmetrize
    S_hat = 0.5 * (S_hat + S_hat.T)
    # Project to PSD by clipping negative eigenvalues
    try:
        evals, evecs = np.linalg.eigh(S_hat)
        evals = np.maximum(evals, 1e-12)
        S_hat = (evecs @ np.diag(evals) @ evecs.T)
        S_hat = 0.5 * (S_hat + S_hat.T)
    except Exception:
        # Fallback: add small jitter on diagonal
        S_hat = S_hat + 1e-12 * I
    return S_hat, float(delta)


def compute_portfolio_fraction(
    f_raw: float,
    symbols: List[str],
    w_vec: np.ndarray,
    cov: np.ndarray,
    f_max: float,
    min_var_eps: float = 1e-8,
) -> float:
    """Portfolio-Kelly fraction adjustment.

    Inputs:
    - f_raw: base Kelly fraction (pre-portfolio)
    - symbols: ordering for w_vec (not used numerically, kept for interface clarity)
    - w_vec: candidate portfolio weights (includes new trade) shape (N,)
    - cov: sample covariance matrix for instruments, shape (N,N)
    - f_max: absolute cap on kelly fraction
    - min_var_eps: minimal variance floor

    Returns f_port = min( f_raw / max(w^T Σ̂ w, eps), f_max )
    """
    w = np.asarray(w_vec, dtype=float).reshape(-1)
    C = np.asarray(cov, dtype=float)
    assert C.shape[0] == C.shape[1] == w.shape[0], "Dimension mismatch: cov and weights"
    S_hat, _ = ledoit_wolf_shrink(C)
    # Variance
    var = float(w @ S_hat @ w)
    if not np.isfinite(var):
        var = float("inf")
    denom = max(var, float(min_var_eps))
    f_port = min(float(f_raw) / denom, float(f_max))
    # Guard non-negative
    if f_port < 0:
        f_port = 0.0
    return f_port

__all__ = ["ledoit_wolf_shrink", "compute_portfolio_fraction"]
