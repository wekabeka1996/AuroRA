from __future__ import annotations

"""
Regime — Manager (trend/grind) with quantile gates + hysteresis
===============================================================

Goal
----
Map streaming market statistics into a *tradeable* regime label {"trend","grind"}
using robust quantile thresholds and hysteresis to reduce flip-flops.

Method
------
We compute a rolling proxy for market activity/volatility (e.g., |returns|) over
window W and a robust center (median). Let q_lo and q_hi be quantiles (e.g.,
0.40 and 0.60 from SSOT-config). We define:

  • grind if vol_proxy ≤ Q(q_lo)
  • trend if vol_proxy ≥ Q(q_hi)
  • otherwise keep previous regime (hysteresis)

Additionally, enforce a minimum dwell time before changing regimes.

Usage
-----
    mgr = RegimeManager(trend_q=0.60, grind_q=0.40, window=1000, min_dwell=250)
    for ret in returns_stream:
        out = mgr.update(ret)
        if out.changed:
            print(out.regime)
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, List, Optional, Tuple

from core.config.loader import get_config, ConfigError


def _quantile(xs: List[float], q: float) -> float:
    if not xs:
        return 0.0
    q = 0.0 if q < 0.0 else 1.0 if q > 1.0 else q
    xs2 = sorted(xs)
    pos = q * (len(xs2) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs2) - 1)
    frac = pos - lo
    return xs2[lo] * (1 - frac) + xs2[hi] * frac


@dataclass
class RegimeState:
    regime: str  # 'trend' | 'grind'
    changed: bool
    q_lo: float
    q_hi: float
    proxy: float
    n: int


class RegimeManager:
    def __init__(
        self,
        *,
        trend_q: Optional[float] = None,
        grind_q: Optional[float] = None,
        window: int = 2000,
        min_dwell: int = 250,
    ) -> None:
        # load defaults from config if not provided
        if trend_q is None or grind_q is None:
            try:
                cfg = get_config()
                if trend_q is None:
                    trend_q = float(cfg.get("regime.manager.trend_quantile", 0.60))
                if grind_q is None:
                    grind_q = float(cfg.get("regime.manager.grind_quantile", 0.40))
            except (ConfigError, Exception):
                trend_q = 0.60 if trend_q is None else trend_q
                grind_q = 0.40 if grind_q is None else grind_q
        if not (0.0 <= grind_q <= trend_q <= 1.0):
            raise ValueError("require 0 <= grind_q <= trend_q <= 1")

        self.q_hi = float(trend_q)
        self.q_lo = float(grind_q)
        self.W = int(max(10, window))
        self.min_dwell = int(max(1, min_dwell))

        self._rets: Deque[float] = deque(maxlen=self.W)
        self._absrets: Deque[float] = deque(maxlen=self.W)
        self._n = 0
        self._ticks_since_change = 0
        self._regime: str = "grind"  # conservative start

    def reset(self) -> None:
        self._rets.clear()
        self._absrets.clear()
        self._n = 0
        self._ticks_since_change = 0
        self._regime = "grind"

    def _proxy(self) -> float:
        # robust volatility proxy: median(|r_t|) over window
        if not self._absrets:
            return 0.0
        return _quantile(list(self._absrets), 0.5)

    def _thresholds(self) -> Tuple[float, float]:
        arr = list(self._absrets)
        if not arr:
            return 0.0, 0.0
        return _quantile(arr, self.q_lo), _quantile(arr, self.q_hi)

    def update(self, ret: float) -> RegimeState:
        r = float(ret)
        self._rets.append(r)
        self._absrets.append(abs(r))
        self._n += 1
        self._ticks_since_change += 1

        proxy = self._proxy()
        t_lo, t_hi = self._thresholds()

        target = self._regime  # default: keep
        if self._n >= self.W // 4:  # minimal warmup
            if proxy <= t_lo:
                target = "grind"
            elif proxy >= t_hi:
                target = "trend"

        changed = False
        if target != self._regime and self._ticks_since_change >= self.min_dwell:
            self._regime = target
            self._ticks_since_change = 0
            changed = True

        return RegimeState(
            regime=self._regime,
            changed=changed,
            q_lo=t_lo,
            q_hi=t_hi,
            proxy=proxy,
            n=self._n,
        )
