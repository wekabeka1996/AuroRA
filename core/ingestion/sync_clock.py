from __future__ import annotations

"""
Ingestion — Sync Clock (Record→Replay/Shadow/Live)
==================================================

Purpose
-------
Provide a deterministic clock that maps **event time** (ts_ns in nanoseconds)
into **wall time** for replay/shadow execution, enforces *no backtracking*, and
allows acceleration (speed > 1) or deceleration (speed < 1). Designed to be
used by replay pipelines before emitting events to downstream modules.

Design
------
- Monotonic wall clock source: time.perf_counter_ns() (immune to system time jumps)
- Mapping: wall_target = wall_anchor + (event_ts - event_anchor) / speed
- Drift policy: if actual wall now is ahead/behind wall_target beyond tolerance,
  we can (optionally) re-anchor to remove accumulated drift in long sessions.
- Anti-backtracking: event_ts must be non-decreasing; wall_target is also clamped
  to be non-decreasing to avoid negative sleeps due to floating rounding.

API
---
- Base protocol: TickClock with now_ns() and sleep_*(...). Implementations:
  • RealTimeClock — thin wrapper over perf_counter_ns(), wall sleeps only
  • ReplayClock   — event_ts→wall mapping with speed, tolerance, re-anchoring
  • ManualClock   — controllable clock for tests

Notes
-----
- Sleep uses a single time.sleep() call; for very long sleeps, callers may
  chunk externally if they need cancellation semantics.
- All units are *nanoseconds* at the API boundary.
"""

import time
import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("aurora.ingestion.sync_clock")
logger.setLevel(logging.INFO)

__all__ = [
    "TickClock",
    "RealTimeClock",
    "ReplayClock",
    "ManualClock",
]


# -------------------- Utilities --------------------

def _ns_to_seconds(ns: int) -> float:
    return 0.0 if ns <= 0 else ns / 1_000_000_000.0


# -------------------- Base protocol --------------------

class TickClock:
    """Abstract clock interface (duck-typed)."""

    def now_ns(self) -> int:  # pragma: no cover - interface
        raise NotImplementedError

    def sleep_until_wall_ns(self, target_wall_ns: int) -> None:  # pragma: no cover - interface
        raise NotImplementedError

    def sleep_until_event_ts_ns(self, event_ts_ns: int) -> None:  # pragma: no cover - interface
        """Optional for replay clocks that track event→wall mapping."""
        raise NotImplementedError


# -------------------- Real-time clock --------------------

class RealTimeClock(TickClock):
    """Real-time clock; useful for live/shadow where pacing = wall time.

    Uses time.perf_counter_ns() for monotonic wall time.
    """

    def __init__(self, max_sleep_ns: Optional[int] = None) -> None:
        self.max_sleep_ns = max_sleep_ns

    def now_ns(self) -> int:
        return time.perf_counter_ns()

    def sleep_until_wall_ns(self, target_wall_ns: int) -> None:
        remaining = target_wall_ns - self.now_ns()
        if remaining > 0:
            # Apply max_sleep_ns clamp if configured
            if self.max_sleep_ns is not None and remaining > self.max_sleep_ns:
                actual_target = self.now_ns() + self.max_sleep_ns
                time.sleep(_ns_to_seconds(self.max_sleep_ns))
            else:
                time.sleep(_ns_to_seconds(remaining))

    # For compatibility in interfaces that call event-based sleeping, just
    # treat event_ts_ns as a wall_ns target (no mapping) — caller should not
    # rely on this in live, but it keeps the interface uniform.
    def sleep_until_event_ts_ns(self, event_ts_ns: int) -> None:
        self.sleep_until_wall_ns(event_ts_ns)


# -------------------- Replay clock --------------------

@dataclass
class ReplayClock(TickClock):
    """Event-time paced clock for record→replay.

    speed: >0, e.g. 1.0 = real-time, 2.0 = 2x faster, 0.5 = half-speed.
    drift_tolerance_ns: if abs(actual - target) exceeds this value, and
                        allow_reanchor=True, re-anchor mapping to reduce drift.
    allow_reanchor: whether to auto-reanchor when drift exceeds tolerance.
    max_sleep_ns: optional clamp for maximum sleep duration per call.
    """

    speed: float = 1.0
    drift_tolerance_ns: int = 5_000_000  # 5 ms default tolerance
    allow_reanchor: bool = True
    max_sleep_ns: Optional[int] = None

    # internal anchors/state
    _event_anchor_ns: Optional[int] = None
    _wall_anchor_ns: Optional[int] = None
    _last_event_ts_ns: Optional[int] = None
    _last_wall_target_ns: Optional[int] = None

    def __post_init__(self) -> None:
        if not (self.speed > 0):
            raise ValueError("speed must be > 0")

    # ---- TickClock API ----

    def now_ns(self) -> int:
        return time.perf_counter_ns()

    def sleep_until_wall_ns(self, target_wall_ns: int) -> None:
        remaining = target_wall_ns - self.now_ns()
        if remaining > 0:
            # Apply max_sleep_ns clamp if configured
            if self.max_sleep_ns is not None and remaining > self.max_sleep_ns:
                actual_target = self.now_ns() + self.max_sleep_ns
                time.sleep(_ns_to_seconds(self.max_sleep_ns))
            else:
                time.sleep(_ns_to_seconds(remaining))

    def sleep_until_event_ts_ns(self, event_ts_ns: int) -> None:
        target = self._target_wall_ns_for_event(event_ts_ns)
        self.sleep_until_wall_ns(target)

    # ---- Public helpers ----

    def start(self, event_anchor_ts_ns: int) -> None:
        """Explicitly set the initial mapping anchor. Optional.
        If not called, the first sleep will auto-anchor.
        """
        self._event_anchor_ns = int(event_anchor_ts_ns)
        self._wall_anchor_ns = self.now_ns()
        self._last_event_ts_ns = None
        self._last_wall_target_ns = None

    # ---- Internals ----

    def _ensure_anchor(self, event_ts_ns: int) -> None:
        if self._event_anchor_ns is None or self._wall_anchor_ns is None:
            # lazily anchor at first event
            self._event_anchor_ns = int(event_ts_ns)
            self._wall_anchor_ns = self.now_ns()
            self._last_wall_target_ns = self._wall_anchor_ns

    def _target_wall_ns_for_event(self, event_ts_ns: int) -> int:
        e = int(event_ts_ns)
        if self._last_event_ts_ns is not None and e < self._last_event_ts_ns:
            raise ValueError(
                f"event timestamp regression: {e} < {self._last_event_ts_ns} (anti-backtracking)"
            )
        self._ensure_anchor(e)
        assert self._event_anchor_ns is not None and self._wall_anchor_ns is not None

        # Compute target wall according to mapping
        delta_event = e - self._event_anchor_ns
        mapped = self._wall_anchor_ns + int(delta_event / self.speed)

        # Clamp to be non-decreasing to avoid tiny negative sleeps on equal ts
        if self._last_wall_target_ns is not None and mapped < self._last_wall_target_ns:
            mapped = self._last_wall_target_ns

        # Drift handling: compare actual now to mapped target
        now = self.now_ns()
        drift = now - mapped
        if self.allow_reanchor and abs(drift) > self.drift_tolerance_ns:
            # Report drift before re-anchoring
            logger.info(
                "replay clock drift detected: drift_ns=%d tolerance_ns=%d re-anchoring",
                drift, self.drift_tolerance_ns
            )
            # Re-anchor so that this event aligns with current wall now
            self._event_anchor_ns = e
            self._wall_anchor_ns = now
            mapped = now

        # Update last seen
        self._last_event_ts_ns = e
        self._last_wall_target_ns = mapped
        return mapped


# -------------------- Manual clock (tests) --------------------

class ManualClock(TickClock):
    """Clock with manually advanced wall time (ns). Useful for deterministic tests."""

    def __init__(self, start_wall_ns: int = 0) -> None:
        self._now = int(start_wall_ns)

    def now_ns(self) -> int:
        return self._now

    def advance_ns(self, delta_ns: int) -> None:
        if delta_ns < 0:
            raise ValueError("cannot go backwards")
        self._now += int(delta_ns)

    def sleep_until_wall_ns(self, target_wall_ns: int) -> None:
        if target_wall_ns < self._now:
            return
        self._now = int(target_wall_ns)

    def sleep_until_event_ts_ns(self, event_ts_ns: int) -> None:
        # In tests, treat event_ts_ns as target wall for simplicity
        self.sleep_until_wall_ns(int(event_ts_ns))
