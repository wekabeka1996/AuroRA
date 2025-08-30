from __future__ import annotations

"""
Universe — Hysteresis gates for stable membership
=================================================

Provide small, dependency-free hysteresis utilities to stabilize set membership
and binary decisions based on a noisy score.

Main constructs
---------------
- Hysteresis: binary gate with add/drop thresholds and minimum dwell time.
- EmaSmoother: exponential moving average for score stabilization.

Usage
-----
    h = Hysteresis(add_thresh=0.6, drop_thresh=0.4, min_dwell=50)
    s = EmaSmoother(alpha=0.2)
    for x in stream:
        z = s.update(x)
        st = h.update(z)
        if st.changed:
            print(st.active)
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class HState:
    active: bool
    changed: bool
    score: float
    ticks_since_change: int


class Hysteresis:
    def __init__(self, *, add_thresh: float, drop_thresh: float, min_dwell: int = 0, start_active: bool = False) -> None:
        if drop_thresh > add_thresh:
            raise ValueError("require drop_thresh <= add_thresh")
        self.add = float(add_thresh)
        self.drop = float(drop_thresh)
        self.min_dwell = int(max(0, min_dwell))
        self.active = bool(start_active)
        self._ticks = 0
        self._score = 0.0

    def reset(self, *, start_active: Optional[bool] = None) -> None:
        if start_active is not None:
            self.active = bool(start_active)
        self._ticks = 0
        self._score = 0.0

    def update(self, score: float) -> HState:
        self._score = float(score)
        self._ticks += 1
        changed = False
        if self.active:
            if self._ticks >= self.min_dwell and self._score <= self.drop:
                self.active = False
                self._ticks = 0
                changed = True
        else:
            if self._ticks >= self.min_dwell and self._score >= self.add:
                self.active = True
                self._ticks = 0
                changed = True
        return HState(active=self.active, changed=changed, score=self._score, ticks_since_change=self._ticks)


class EmaSmoother:
    def __init__(self, *, alpha: float = 0.2, init: Optional[float] = None) -> None:
        if not (0.0 < alpha <= 1.0):
            raise ValueError("alpha in (0,1]")
        self.alpha = float(alpha)
        self._y: Optional[float] = float(init) if init is not None else None

    def update(self, x: float) -> float:
        x = float(x)
        if self._y is None:
            self._y = x
        else:
            self._y = self.alpha * x + (1.0 - self.alpha) * self._y
        return self._y

    def value(self) -> Optional[float]:
        return self._y


__all__ = ["Hysteresis", "HState", "EmaSmoother"]