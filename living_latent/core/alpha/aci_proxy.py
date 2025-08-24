from __future__ import annotations
import numpy as np

"""ACI Proxy utilities.

Transforms a raw series (e.g., residuals) into an instability proxy capturing
local volatility dynamics.
"""

def realized_vol(series: np.ndarray, window: int) -> np.ndarray:
    series = np.asarray(series, dtype=float)
    n = series.size
    out = np.full(n, np.nan, dtype=float)
    if window <= 1:
        return np.abs(series)
    cumsum = np.cumsum(np.insert(series, 0, 0.0))
    cumsum2 = np.cumsum(np.insert(series * series, 0, 0.0))
    for i in range(window, n + 1):
        s = cumsum[i] - cumsum[i - window]
        s2 = cumsum2[i] - cumsum2[i - window]
        mean = s / window
        var = (s2 / window) - mean * mean
        if var < 0:
            var = 0.0
        out[i - 1] = np.sqrt(var)
    return out

def compute_aci_proxy(series: np.ndarray, window: int = 64, smooth: int = 8, eps: float = 1e-9) -> np.ndarray:
    series = np.asarray(series, dtype=float)
    vol = realized_vol(series, window)
    finite = vol[np.isfinite(vol)]
    scale = np.median(finite) if finite.size else 1.0
    if not np.isfinite(scale) or scale <= 0:
        scale = 1.0
    proxy = vol / (scale + eps)
    if smooth > 1:
        alpha = 2.0 / (smooth + 1.0)
        ema = np.nan
        for i, v in enumerate(proxy):
            if not np.isfinite(v):
                continue
            if not np.isfinite(ema):
                ema = v
            else:
                ema = alpha * v + (1 - alpha) * ema
            proxy[i] = ema
    return proxy

def rolling_corr(x: np.ndarray, y: np.ndarray, window: int) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    assert x.shape == y.shape
    n = x.size
    out = np.full(n, np.nan, dtype=float)
    if window <= 1:
        return out
    cx = np.cumsum(np.insert(x, 0, 0.0))
    cy = np.cumsum(np.insert(y, 0, 0.0))
    cxx = np.cumsum(np.insert(x * x, 0, 0.0))
    cyy = np.cumsum(np.insert(y * y, 0, 0.0))
    cxy = np.cumsum(np.insert(x * y, 0, 0.0))
    for i in range(window, n + 1):
        sx = cx[i] - cx[i - window]
        sy = cy[i] - cy[i - window]
        sxx = cxx[i] - cxx[i - window]
        syy = cyy[i] - cyy[i - window]
        sxy = cxy[i] - cxy[i - window]
        mx = sx / window
        my = sy / window
        cov = (sxy / window) - mx * my
        varx = (sxx / window) - mx * mx
        vary = (syy / window) - my * my
        if varx <= 0 or vary <= 0:
            out[i - 1] = 0.0
        else:
            out[i - 1] = cov / np.sqrt(varx * vary)
    return out

__all__ = ["compute_aci_proxy","realized_vol","rolling_corr"]
