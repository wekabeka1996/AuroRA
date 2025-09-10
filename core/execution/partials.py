from __future__ import annotations

"""
Execution — Partial fills and slicing policy
===========================================

Implements a small, idempotent slicing state machine for breaking a target order
into child slices, taking into account liquidity and (optionally) an estimated
fill rate. The goal is to reduce footprint/adverse selection while maintaining
throughput.

Core ideas
----------
- The *remaining* target quantity Q_rem is allocated into slices of size
  q = clip(α * Q_rem, q_min, q_max), where α ∈ (0,1) is a decay factor.
- Optionally modulate by expected P(fill): q ← q * P(fill) to avoid large
  resting orders in thin books.
- Each slice is assigned a deterministic idempotency key based on (order_id,
  slice_idx), allowing safe retries.

This module does **not** place orders; it only produces slicing decisions and
maintains per-order state. Connect it to exchange adapters.
"""

from dataclasses import dataclass
import math


@dataclass
class SliceDecision:
    order_id: str
    slice_idx: int
    qty: float
    remaining_after: float
    key: str  # idempotency key


class PartialSlicer:
    def __init__(
        self,
        *,
        alpha: float = 0.5,
        q_min: float = 0.0,
        q_max: float = float("inf"),
        use_p_fill: bool = True,
    ) -> None:
        if not (0.0 < alpha < 1.0):
            raise ValueError("alpha must be in (0,1)")
        self.alpha = float(alpha)
        self.q_min = float(q_min)
        self.q_max = float(q_max)
        self.use_p_fill = bool(use_p_fill)
        self._state: dict[str, dict[str, float]] = {}

    def _state_of(self, order_id: str) -> dict[str, float]:
        s = self._state.get(order_id)
        if s is None:
            # last_fill stores the last registered fill quantity to make register_fill idempotent
            s = {"idx": 0.0, "filled": 0.0, "target": 0.0, "last_fill": None}
            self._state[order_id] = s
        return s

    def start(self, order_id: str, target_qty: float) -> None:
        s = self._state_of(order_id)
        s["idx"] = 0.0
        s["filled"] = 0.0
        s["last_fill"] = None
        s["target"] = float(target_qty)

    def register_fill(self, order_id: str, fill_qty: float) -> float:
        s = self._state_of(order_id)
        fq = float(fill_qty)
        # Idempotency: if the last registered fill for this order is (close to) the
        # incoming quantity, assume a duplicate delivery and do not double-count it.
        last = s.get("last_fill")
        if last is not None and math.isclose(last, fq, rel_tol=1e-9, abs_tol=1e-12):
            rem = max(0.0, s["target"] - s["filled"])
            return rem

        # Otherwise apply the fill and remember it as last_fill.
        s["filled"] = s.get("filled", 0.0) + fq
        s["last_fill"] = fq
        rem = max(0.0, s["target"] - s["filled"])
        return rem

    def remaining(self, order_id: str) -> float:
        s = self._state_of(order_id)
        return max(0.0, s["target"] - s["filled"])

    def next_slice(self, order_id: str, *, p_fill: float | None = None) -> SliceDecision | None:
        s = self._state_of(order_id)
        rem = max(0.0, s["target"] - s["filled"])
        if rem <= 0.0:
            return None
        idx = int(s["idx"]) + 1
        s["idx"] = float(idx)

        # base size: geometric decay of remaining
        q = self.alpha * rem
        if self.use_p_fill and p_fill is not None:
            q *= max(0.0, min(1.0, float(p_fill)))
        # clamp
        if q < self.q_min:
            q = self.q_min
        if q > self.q_max:
            q = self.q_max
        # don't exceed remaining (this is the key fix)
        q = min(q, rem)

        # Additional safety: if this would be the last slice and q > rem, use rem
        if rem - q < self.q_min and q > rem:
            q = rem

        key = f"{order_id}:{idx}"
        return SliceDecision(order_id=order_id, slice_idx=idx, qty=q, remaining_after=rem - q, key=key)

    def cancel(self, order_id: str) -> None:
        self._state.pop(order_id, None)


__all__ = ["PartialSlicer", "SliceDecision"]
