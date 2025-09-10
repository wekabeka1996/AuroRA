from __future__ import annotations

"""
XAI — Alerts
============

Alerting primitives used in live runs to surface operational and
statistical issues:
  • NoTradesAlert: detects lack of tradeable decisions over a wall-time window
  • DenySpikeAlert: detects spikes in deny rate (action == 'deny')
  • CalibrationDriftAlert: monitors ECE drift via PrequentialMetrics
  • CvarBreachAlert: monitors empirical CVaR against SSOT limit

Design goals
------------
- Pure Python, no external deps, deterministic
- Time-based rolling windows using deques (ts_ns in nanoseconds)
- Debouncing: min_interval_ns between notifications per alert
- Safe defaults; thresholds can be overridden via SSOT-config
"""

from collections import deque
from dataclasses import dataclass

from core.calibration.calibrator import PrequentialMetrics
from core.config.loader import ConfigError, get_config

NS_PER_SEC = 1_000_000_000

# -------------------- helpers --------------------

class RollingWindow:
    """Time-based rolling window for values; stores (ts_ns, value)."""

    def __init__(self, window_ns: int) -> None:
        self._win = int(window_ns)
        self._dq: deque[tuple[int, float]] = deque()

    def push(self, ts_ns: int, value: float) -> None:
        t = int(ts_ns)
        self._dq.append((t, float(value)))
        self._prune(t)

    def _prune(self, now_ns: int) -> None:
        cutoff = now_ns - self._win
        dq = self._dq
        while dq and dq[0][0] < cutoff:
            dq.popleft()

    def stats(self, now_ns: int | None = None) -> tuple[int, float, float]:
        """Return (count, mean, sum) over current window."""
        if not self._dq:
            return 0, 0.0, 0.0
        if now_ns is not None:
            self._prune(int(now_ns))
        n = len(self._dq)
        s = sum(v for _, v in self._dq)
        return n, (s / n), s

    def values(self) -> list[float]:
        return [v for _, v in self._dq]


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    q = 0.0 if q < 0.0 else 1.0 if q > 1.0 else q
    xs2 = sorted(xs)
    pos = q * (len(xs2) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(xs2) - 1)
    frac = pos - lo
    return xs2[lo] * (1 - frac) + xs2[hi] * frac


# -------------------- base --------------------

@dataclass
class AlertResult:
    triggered: bool
    message: str


class BaseAlert:
    def __init__(self, *, min_interval_ns: int = 30 * NS_PER_SEC) -> None:
        self._min_interval = int(min_interval_ns)
        self._last_ts: int | None = None

    def _debounced(self, ts_ns: int) -> bool:
        if self._last_ts is None or ts_ns - self._last_ts >= self._min_interval:
            self._last_ts = ts_ns
            return True
        return False


# -------------------- specific alerts --------------------

class NoTradesAlert(BaseAlert):
    """Alert when emitted *tradeable* decisions drop to zero over a window."""

    def __init__(self, *, window_sec: int = 60, min_interval_ns: int = 60 * NS_PER_SEC) -> None:
        super().__init__(min_interval_ns=min_interval_ns)
        self._win = RollingWindow(window_sec * NS_PER_SEC)
        try:
            cfg = get_config()
            self._window_ns = int(cfg.get("xai.alerts.no_trades_window_ns", window_sec * NS_PER_SEC))
        except (ConfigError, Exception):
            self._window_ns = window_sec * NS_PER_SEC

    def update(self, ts_ns: int, action: str) -> AlertResult | None:
        self._win.push(ts_ns, 1.0 if action in ("enter", "exit") else 0.0)
        n, mean, s = self._win.stats()
        if n == 0:
            return None
        # If sum over window is zero, trigger
        if s <= 0.0 and self._debounced(ts_ns):
            return AlertResult(True, f"NoTradesAlert: no tradeable decisions in last {self._window_ns/NS_PER_SEC:.0f}s")
        return None


class DenySpikeAlert(BaseAlert):
    """Alert when deny rate spikes above a threshold over a rolling window."""

    def __init__(self, *, window_sec: int = 60, rate_thresh: float = 0.8, min_interval_ns: int = 60 * NS_PER_SEC) -> None:
        super().__init__(min_interval_ns=min_interval_ns)
        self._win = RollingWindow(window_sec * NS_PER_SEC)
        self._rate_thresh = float(rate_thresh)
        try:
            cfg = get_config()
            self._rate_thresh = float(cfg.get("xai.alerts.deny_rate_thresh", rate_thresh))
        except (ConfigError, Exception):
            pass

    def update(self, ts_ns: int, action: str) -> AlertResult | None:
        self._win.push(ts_ns, 1.0 if action == "deny" else 0.0)
        n, mean, s = self._win.stats()
        if n == 0:
            return None
        if mean >= self._rate_thresh and self._debounced(ts_ns):
            return AlertResult(True, f"DenySpikeAlert: deny rate {mean:.2f} >= threshold {self._rate_thresh:.2f}")
        return None


class CalibrationDriftAlert(BaseAlert):
    """Alert on calibration drift measured by prequential ECE."""

    def __init__(self, *, bins: int = 10, ece_thresh: float = 0.05, min_interval_ns: int = 60 * NS_PER_SEC) -> None:
        super().__init__(min_interval_ns=min_interval_ns)
        self._m = PrequentialMetrics(n_bins=bins)
        self._ece_thresh = float(ece_thresh)
        try:
            cfg = get_config()
            self._ece_thresh = float(cfg.get("xai.alerts.ece_thresh", ece_thresh))
        except (ConfigError, Exception):
            pass

    def update(self, ts_ns: int, p: float, y: int) -> AlertResult | None:
        self._m.update(p, y)
        metrics = self._m.metrics()
        ece = metrics.ece
        if ece is not None and ece >= self._ece_thresh and self._debounced(ts_ns):
            return AlertResult(True, f"CalibrationDriftAlert: ECE {ece:.3f} >= threshold {self._ece_thresh:.3f}")
        return None


class CvarBreachAlert(BaseAlert):
    """Empirical CVaR monitor vs SSOT-config limit.

    Uses a rolling window of returns (PnL as fraction of equity per trade). For
    losses (negative returns), computes empirical CVaR at 'alpha' and triggers
    if CVaR magnitude exceeds configured limit.
    """

    def __init__(self, *, window_size: int = 2000, alpha: float = 0.95, min_interval_ns: int = 60 * NS_PER_SEC) -> None:
        super().__init__(min_interval_ns=min_interval_ns)
        self._alpha = float(alpha)
        self._rets: deque[float] = deque(maxlen=int(window_size))
        try:
            cfg = get_config()
            self._limit = float(cfg.get("risk.cvar.limit", 0.02))
            self._alpha = float(cfg.get("risk.cvar.alpha", alpha))
        except (ConfigError, Exception):
            self._limit = 0.02

    def update(self, ts_ns: int, ret: float) -> AlertResult | None:
        self._rets.append(float(ret))
        if len(self._rets) < 50:
            return None
        losses = sorted([-r for r in self._rets if r < 0.0])  # positive magnitudes of losses
        if not losses:
            return None
        # empirical VaR at alpha: quantile of loss distribution
        var = _quantile(losses, self._alpha)
        # empirical CVaR = mean of tail beyond VaR
        tail = [l for l in losses if l >= var]
        cvar = sum(tail) / max(1, len(tail))
        if cvar >= self._limit and self._debounced(ts_ns):
            return AlertResult(True, f"CvarBreachAlert: CVaR {cvar:.4f} >= limit {self._limit:.4f} at alpha={self._alpha}")
        return None


__all__ = [
    "AlertResult",
    "NoTradesAlert",
    "DenySpikeAlert",
    "CalibrationDriftAlert",
    "CvarBreachAlert",
]


# -------------------- minimal routing helper for tests --------------------

def route_reason_for_context(ctx: dict) -> str:
    """Return a normalized reason string for a given minimal context.

    This is a lightweight helper used by tests to ensure a stable string output.
    It does not perform any side effects and relies only on a few common keys.
    """
    try:
        latency = float(ctx.get("latency_ms", 0.0) or 0.0)
    except Exception:
        latency = 0.0
    if latency > 0:
        return "latency_high" if latency >= 1000.0 else "latency"

    reason = str(ctx.get("reason", ""))
    if reason:
        return reason

    # Fallbacks based on boolean flags
    if ctx.get("trap_flag"):
        return "trap_guard"
    if ctx.get("slippage_exceeded"):
        return "slippage_guard"
    if ctx.get("expected_return_low"):
        return "expected_return_gate"

    return "ok"
