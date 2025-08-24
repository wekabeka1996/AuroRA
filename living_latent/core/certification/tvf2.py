"""TVF 2.0 utilities: DCTS (Distributional Conformal Transfer Score) and Δ-invariants.

Contract per AUR-TVF-801.
"""
from __future__ import annotations
from typing import Mapping, Dict, Iterable, Sequence
import numpy as np

__all__ = ["compute_dcts", "delta_invariants", "quantile_grid"]

# --- Core helpers ---

def quantile_grid(residuals: np.ndarray, alphas: Sequence[float] = (0.1, 0.2, 0.3)) -> Dict[float, float]:
    """Compute tail quantile map q(1-alpha) for given alpha grid.

    residuals : 1D array of residuals (errors). We assume symmetric usage but
    treat quantiles directly.
    Returns dict {alpha: q_{1-alpha}}.
    """
    r = np.asarray(residuals, dtype=float)
    if r.ndim != 1:
        r = r.reshape(-1)
    out: Dict[float, float] = {}
    for a in alphas:
        a_f = float(a)
        if not 0 < a_f < 1:
            continue
        q = np.quantile(r, 1 - a_f)
        out[a_f] = float(q)
    return out


def compute_dcts(residuals_T: np.ndarray, qhat_S: Mapping[float, float]) -> float:
    """Compute Distributional Conformal Transfer Score (DCTS).

    Idea: measure alignment of target domain tail quantiles with source domain
    estimates. For a set of alpha in qhat_S we compute target quantiles q_T(1-alpha),
    evaluate relative deviation to source q_S, then convert to a [0,1] score:

        dcts = 1 - mean( clip( |q_T - q_S| / ( |q_S| + eps ), 0, 1 ) )

    Perfect match => 1. Large deviation => closer to 0.
    If source quantile is near zero we fallback to absolute scale using MAD.
    """
    rT = np.asarray(residuals_T, dtype=float).reshape(-1)
    if len(qhat_S) == 0 or rT.size == 0:
        return float('nan')
    eps = 1e-9
    # robust scale for fallback
    mad = np.median(np.abs(rT - np.median(rT))) + eps
    errs = []
    for a, qS in qhat_S.items():
        try:
            qT = np.quantile(rT, 1 - float(a))
        except Exception:
            continue
        denom = abs(qS) if abs(qS) > 5 * eps else mad
        rel = abs(qT - qS) / (denom + eps)
        # Clamp to 1.0 explicitly to avoid type inference issues
        if rel > 1.0:
            rel = 1.0
        errs.append(float(rel))
    if not errs:
        return float('nan')
    return float(1.0 - float(np.mean(errs)))


def delta_invariants(src: Dict[str, float], tgt: Dict[str, float]) -> Dict[str, float]:
    """Compute deltas (tgt - src) for tail invariant snapshot fields.

    Expected keys: 'xi', 'theta_e', 'lambda_U'. Missing keys produce None.
    Returns mapping {'d_xi','d_theta_e','d_lambda_U'}.
    """
    keys = ['xi', 'theta_e', 'lambda_U']
    out: Dict[str, float] = {}
    for k in keys:
        sk = src.get(k) if isinstance(src, dict) else None  # type: ignore
        tk = tgt.get(k) if isinstance(tgt, dict) else None  # type: ignore
        if sk is None or tk is None:
            out[f'd_{k}'] = None  # type: ignore
        else:
            out[f'd_{k}'] = float(tk) - float(sk)
    return out
