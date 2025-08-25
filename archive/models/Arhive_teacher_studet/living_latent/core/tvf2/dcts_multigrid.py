from __future__ import annotations
from dataclasses import dataclass
from typing import List, Dict, Mapping, Sequence
import numpy as np

try:  # reuse existing implementation
    from living_latent.core.certification.tvf2 import compute_dcts
except Exception:  # pragma: no cover
    compute_dcts = None  # type: ignore

__all__ = [
    'DCTSGridConfig',
    'compute_dcts_single',
    'compute_dcts_for_grid',
    'compute_dcts_multigrid'
]

@dataclass
class DCTSGridConfig:
    grids: List[float]
    base_window: int
    aggregator: str = "median_min"  # median|min, median_min, trimmed_mean:p=0.2
    alphas: Sequence[float] | None = None  # optional override of quantile grid


def compute_dcts_single(residuals_T: np.ndarray, qhat_S: Mapping[float, float]) -> float:
    if compute_dcts is None:
        return float('nan')
    return float(compute_dcts(np.asarray(residuals_T), qhat_S))


def _resample_or_window(residuals: np.ndarray, window: int) -> np.ndarray:
    """Apply rolling-median smoothing to residuals to emulate scale adjustment.
    This keeps semantics deterministic and cheap. We avoid resizing dataset; instead we smooth more for larger window.
    """
    if window <= 1:
        return residuals
    r = residuals
    # simple centered rolling median using stride trick fallback
    k = int(window)
    if k >= r.size:
        return np.repeat(np.median(r), r.size)
    out = np.empty_like(r)
    half = k // 2
    for i in range(r.size):
        lo = max(0, i - half)
        hi = min(r.size, i + half + 1)
        out[i] = np.median(r[lo:hi])
    return out


def compute_dcts_for_grid(residuals_T: np.ndarray, qhat_S: Mapping[float, float], base_window: int, grid: float) -> float:
    g = float(grid)
    win = max(1, int(round(base_window * g)))
    smoothed = _resample_or_window(np.asarray(residuals_T), win)
    return compute_dcts_single(smoothed, qhat_S)


def compute_dcts_multigrid(residuals_T: np.ndarray, qhat_S: Mapping[float, float], cfg: DCTSGridConfig) -> Dict[str, object]:
    """Compute multigrid DCTS metrics.

    Returns dict with keys: 'grids', 'robust', 'min'.
    """
    results: Dict[str, float] = {}
    vals: List[float] = []
    for g in cfg.grids:
        try:
            v = compute_dcts_for_grid(residuals_T, qhat_S, cfg.base_window, g)
            if np.isfinite(v):
                results[str(g)] = float(v)
                vals.append(float(v))
        except Exception:
            continue
    robust_value = float('nan')
    min_value = float('nan')
    if vals:
        arr = np.array(vals, dtype=float)
        arr_sorted = np.sort(arr)
        min_value = float(arr.min())
        agg = cfg.aggregator or 'median_min'
        if agg.startswith('trimmed_mean'):
            p = 0.2
            if ':' in agg:
                try:
                    part = agg.split(':',1)[1]
                    if part.startswith('p='):
                        p = float(part[2:])
                except Exception:
                    p = 0.2
            k = int(len(arr_sorted)*p)
            core = arr_sorted[k: len(arr_sorted)-k] if k < len(arr_sorted)//2 else arr_sorted
            if core.size:
                robust_value = float(core.mean())
            else:
                robust_value = float(np.median(arr_sorted))
        elif agg == 'median':
            robust_value = float(np.median(arr_sorted))
        else:  # median_min or fallback
            robust_value = float(np.median(arr_sorted))
    return {
        'grids': results,
        'robust': {'value': robust_value, 'grids': cfg.grids},
        'min': {'value': min_value},
    }
