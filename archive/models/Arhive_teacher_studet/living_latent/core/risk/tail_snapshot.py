"""Snapshot utilities for tail metrics (RSK-203).

Provides a thin wrapper around core.tail_metrics to compute and persist
an atomic JSON snapshot for monitoring / acceptance layers.
"""
from __future__ import annotations
from pathlib import Path
import json
import numpy as np
from typing import Dict, Any

from living_latent.core.tail_metrics import (
    hill_tail_index, extremal_index_runs, upper_tail_dependence, InsufficientTailSamples
)


def snapshot_tail_metrics(x: np.ndarray, y: np.ndarray | None = None, regime: str = "default",
                           tail_q: float = 0.95, out_json: Path | None = None) -> Dict[str, Any]:
    """Compute tail metrics snapshot.

    Parameters
    ----------
    x : np.ndarray
        Primary series (e.g., residuals or PnL increments).
    y : np.ndarray | None
        Optional second series for tail dependence; if None, lambda_U set to NaN.
    regime : str
        Regime label to attach (e.g., 'stable', 'shock').
    tail_q : float
        Quantile threshold for extremal index and tail dependence.
    out_json : Path | None
        If provided, writes JSON snapshot (atomic temp + rename).

    Returns
    -------
    dict
        { 'xi': float, 'k': int, 'theta_e': float, 'lambda_U': float, 'n_tail': int, 'regime': str }
    """
    x = np.asarray(x, dtype=float)
    clean = x[~np.isnan(x)]
    n = clean.size
    xi = float('nan'); k = 0
    try:
        hres = hill_tail_index(clean, k=None, min_k=10)
        xi = hres.xi; k = hres.k
    except InsufficientTailSamples:
        pass
    theta_e = extremal_index_runs(clean, threshold_q=tail_q)
    if y is not None:
        lambda_u = upper_tail_dependence(clean, np.asarray(y, dtype=float), threshold_q=tail_q)
    else:
        lambda_u = float('nan')
    # tail count
    if n > 0:
        u = np.quantile(clean, tail_q)
        n_tail = int((clean > u).sum())
    else:
        n_tail = 0
    payload = {
        'xi': xi,
        'k': k,
        'theta_e': theta_e,
        'lambda_U': lambda_u,
        'n_tail': n_tail,
        'regime': regime,
        'q': tail_q,
        'n': n
    }
    if out_json is not None:
        out_json = Path(out_json)
        tmp = out_json.with_suffix(out_json.suffix + '.tmp')
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        tmp.replace(out_json)
    return payload

__all__ = ["snapshot_tail_metrics"]
