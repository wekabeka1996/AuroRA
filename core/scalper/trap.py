from __future__ import annotations

"""
Implement TRAP v2 metrics for fake-wall detection.

Window: 1–3s, levels L=5.
Inputs (stream): per-tick L1..L5 depth changes and trade prints.
Compute:
  cancel_rate = sum(max(Δcancel_i,0))/Δt
  repl_rate   = sum(max(Δadd_i,0))/Δt
  trades_cnt  = count trades within window
  trap_raw    = (cancel_rate - repl_rate) / max(1, trades_cnt)

Standardize trap_raw → trap_z using rolling robust stats:
  - percentile z: z = (trap_raw - p50) / (p90 - p10), clipped to [-4, +4]
    (maintain rolling percentiles via P²/TDigest)

Output dataclass TrapMetrics:
  repl_rate: float
  cancel_rate: float
  trap_raw: float
  trap_z: float
  n_trades: int
  flag: bool  # gate decision

Flag rule:
  flag = trap_z >= z_threshold
         or (sign(OBI) != sign(TFI) and cancel_rate >= p90_cancel)

Config keys (read via pretrade):
  trap.enabled: bool
  trap.window_s: float (default 2.0)
  trap.levels: int (default 5)
  trap.z_threshold: float (default 1.64 ~ p95)
  trap.cancel_pctl: int (default 90)

Provide pure functions + a small stateful window class for streaming updates.
Type hints, docstrings, no external network deps.
"""

from dataclasses import dataclass
from typing import Iterable, Optional, Tuple, List, Literal

import numpy as np


@dataclass(frozen=True)
class TrapMetrics:
    repl_rate: float
    cancel_rate: float
    trap_raw: float
    trap_z: float
    n_trades: int
    flag: bool


class RollingPercentiles:
    """Simple rolling percentile estimator backed by a finite buffer.

    This is a pragmatic implementation for tests and small windows. For production
    a streaming estimator (e.g., P²/TDigest) is recommended.
    """

    def __init__(self, maxlen: int = 240) -> None:
        self._buf: list[float] = []
        self._maxlen = maxlen

    def add(self, x: float) -> None:
        self._buf.append(float(x))
        if len(self._buf) > self._maxlen:
            # drop oldest
            self._buf.pop(0)

    def percentiles(self, pcts: Iterable[float]) -> list[float]:
        if not self._buf:
            return [0.0 for _ in pcts]
        arr = np.array(self._buf, dtype=float)
        return [float(np.percentile(arr, p)) for p in pcts]

    def pctl(self, p: float) -> float:
        return self.percentiles([p])[0]


def _rate(sum_vals: float, dt_s: float) -> float:
    return float(sum_vals) / float(dt_s) if dt_s > 0 else 0.0


def compute_trap_raw(
    cancel_deltas: Iterable[float], add_deltas: Iterable[float], trades_cnt: int, dt_s: float
) -> Tuple[float, float, float]:
    """Compute cancel_rate, repl_rate, trap_raw from a single window snapshot."""
    cancel_sum = float(np.sum(np.maximum(np.array(list(cancel_deltas), dtype=float), 0.0)))
    add_sum = float(np.sum(np.maximum(np.array(list(add_deltas), dtype=float), 0.0)))
    cancel_rate = _rate(cancel_sum, dt_s)
    repl_rate = _rate(add_sum, dt_s)
    denom = float(max(1, int(trades_cnt)))
    trap_raw = (cancel_rate - repl_rate) / denom
    return cancel_rate, repl_rate, trap_raw


def robust_z(trap_raw: float, p10: float, p50: float, p90: float, clip: float = 4.0) -> float:
    spread = max(1e-6, (p90 - p10))
    z = (float(trap_raw) - float(p50)) / spread
    return float(np.clip(z, -clip, clip))


class TrapWindow:
    """Stateful window to compute TRAP metrics and robust z-score.

    Feed with per-window aggregates (cancel/add deltas at L1..Lk and trade count)
    and it will maintain rolling percentiles of trap_raw and cancel_rate.
    """

    def __init__(self, window_s: float = 2.0, levels: int = 5, history: int = 240) -> None:
        self.window_s = float(window_s)
        self.levels = int(levels)
        self._hist_trap = RollingPercentiles(maxlen=history)
        self._hist_cancel = RollingPercentiles(maxlen=history)

    def update(
        self,
        cancel_deltas: Iterable[float],
        add_deltas: Iterable[float],
        trades_cnt: int,
        *,
        z_threshold: float = 1.64,
        cancel_pctl: int = 90,
        obi_sign: Optional[int] = None,
        tfi_sign: Optional[int] = None,
    ) -> TrapMetrics:
        cancel_rate, repl_rate, trap_raw = compute_trap_raw(cancel_deltas, add_deltas, trades_cnt, self.window_s)

        # Update rolling stats first, then compute z based on pre-update or post-update?
        # We'll compute z using pre-update stats to avoid self-influencing current z.
        p10, p50, p90 = self._hist_trap.percentiles([10, 50, 90])
        z = robust_z(trap_raw, p10, p50, p90)

        # Maintain histories
        self._hist_trap.add(trap_raw)
        self._hist_cancel.add(cancel_rate)

        p90_cancel = self._hist_cancel.pctl(cancel_pctl)
        conflict = (obi_sign is not None and tfi_sign is not None and int(np.sign(obi_sign)) != int(np.sign(tfi_sign)))
        flag = (z >= float(z_threshold)) or (conflict and cancel_rate >= p90_cancel)

        return TrapMetrics(
            repl_rate=repl_rate,
            cancel_rate=cancel_rate,
            trap_raw=trap_raw,
            trap_z=z,
            n_trades=int(trades_cnt),
            flag=bool(flag),
        )


# --- Normalized book_delta handling for TRAP v2.1 ---

BookAction = Literal["add", "cancel", "trade"]


@dataclass(frozen=True)
class BookDelta:
    ts: float  # seconds
    side: Literal["bid", "ask"]
    price: float
    size: float
    action: BookAction


def _estimate_replenish_latency_ms(events: List[BookDelta], price_eps: float = 1e-6) -> float:
    """Estimate typical replenish latency: time between cancel and next add at nearby price on same side.

    Returns median latency in milliseconds over pairs found; if none found, returns a large sentinel (e.g., 1000ms).
    """
    latencies: List[float] = []
    last_cancel_by_side_price: dict[tuple[str, int], float] = {}
    for ev in sorted(events, key=lambda e: e.ts):
        key = (ev.side, int(round(ev.price / max(price_eps, 1e-9))))
        if ev.action == "cancel":
            last_cancel_by_side_price[key] = ev.ts
        elif ev.action == "add":
            t0 = last_cancel_by_side_price.get(key)
            if t0 is not None:
                latencies.append(max(0.0, (ev.ts - t0) * 1000.0))
                # reset to avoid chaining
                last_cancel_by_side_price.pop(key, None)
    if not latencies:
        return 1000.0
    arr = np.array(latencies, dtype=float)
    return float(np.median(arr))


def _cancel_add_sums(events: List[BookDelta], levels: int = 5) -> tuple[List[float], List[float]]:
    """Aggregate positive cancel/add deltas across L1..Lk.

    Here we do not maintain explicit levels by price distance; for a simple heuristic we sum per event type.
    Return two lists (length=levels) that can be fed into compute_trap_raw.
    """
    cancel_sum = sum(ev.size for ev in events if ev.action == "cancel")
    add_sum = sum(ev.size for ev in events if ev.action == "add")
    # Distribute sums uniformly across levels as a placeholder; tests will use totals only
    cancels = [cancel_sum / levels] * levels
    adds = [add_sum / levels] * levels
    return cancels, adds


def trap_score_from_features(cancel_ratio: float, replenish_latency_ms: float) -> float:
    """Map features to [0,1] score: higher when cancels dominate and replenish is very fast.

    cancel_ratio in [0,1]; faster replenish => higher score. Use simple smooth mapping.
    """
    # Emphasize high cancel dominance
    c = 1.0 / (1.0 + np.exp(-8.0 * (float(cancel_ratio) - 0.5)))  # sigmoid centered at 0.5
    # Map latency to [0,1], 0ms -> 1.0; 1000ms -> ~0.0
    r = float(np.clip(np.exp(-float(replenish_latency_ms) / 250.0), 0.0, 1.0))
    score = float(np.clip(0.6 * c + 0.4 * r, 0.0, 1.0))
    return score


def trap_from_book_deltas(
    events: List[BookDelta], *, window_s: float = 2.0, levels: int = 5
) -> tuple[float, float, float, float]:
    """Compute trap features from normalized book_delta events within a window.

    Returns (cancel_ratio, replenish_latency_ms, cancel_sum, add_sum).
    """
    cancels, adds = _cancel_add_sums(events, levels=levels)
    cancel_sum = float(np.sum(cancels))
    add_sum = float(np.sum(adds))
    denom = max(1e-6, cancel_sum + add_sum)
    cancel_ratio = cancel_sum / denom
    rep_ms = _estimate_replenish_latency_ms(events)
    return cancel_ratio, rep_ms, cancel_sum, add_sum

