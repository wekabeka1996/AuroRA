from __future__ import annotations
import math
from typing import Iterable, Tuple

import numpy as np

EPS = 1e-9

__all__ = ["surprisal_v2", "winsorized_p95"]

def huber(r: float, delta: float = 1.345) -> float:
    if r <= delta:
        return 0.5 * r * r
    return delta * (r - 0.5 * delta)

def surprisal_v2(y: float, mu: float, sigma: float, delta: float = 1.345) -> float:
    sigma_eff = max(sigma, 1e-6 * max(1.0, abs(mu)))
    r = abs(y - mu) / (sigma_eff + EPS)
    h = huber(r, delta=delta)
    return math.log1p(h)

def winsorized_p95(values: Iterable[float]) -> float:
    arr = np.array([v for v in values if np.isfinite(v)], dtype=float)
    if arr.size == 0:
        return float("nan")
    lo, hi = np.percentile(arr, [1, 99])
    arr = np.clip(arr, lo, hi)
    return float(np.percentile(arr, 95))
