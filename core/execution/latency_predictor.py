"""Latency predictor (EMA + p90 window) skeleton.

Used in ExecutionService before calling RouterV2.
"""
from __future__ import annotations
from collections import deque
from typing import Deque, Optional

class LatencyPredictor:
    def __init__(self, *, alpha: float = 0.2, window: int = 200):
        self.alpha = float(alpha)
        self.window = int(window)
        self._ema: Optional[float] = None
        self._samples: Deque[float] = deque(maxlen=self.window)

    def update(self, latency_ms: float) -> None:
        x = float(latency_ms)
        self._samples.append(x)
        if self._ema is None:
            self._ema = x
        else:
            self._ema = self.alpha * x + (1 - self.alpha) * self._ema

    def predict(self) -> float:
        if not self._samples:
            return self._ema or 0.0
        # exact p90
        arr = sorted(self._samples)
        pos = 0.9 * (len(arr) - 1)
        lo = int(pos); hi = min(lo + 1, len(arr) - 1)
        frac = pos - lo
        p90 = arr[lo] * (1 - frac) + arr[hi] * frac
        base = self._ema if self._ema is not None else p90
        pred = 0.5 * base + 0.5 * p90
        # cap by 1.25 * p90 to avoid spikes
        return min(pred, p90 * 1.25)

__all__ = ['LatencyPredictor']
