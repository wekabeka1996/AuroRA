from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import time

import numpy as np


@dataclass
class GuardState:
    armed: bool = True
    cooloff_until: float = 0.0  # epoch seconds
    halted: bool = False


class HealthGuard:
    """Latency p95 guard with WARN→COOL_OFF→HALT escalations.

    - record(latency_ms): insert a sample and evaluate p95 over the last window_sec.
      If p95 > threshold_ms: emit WARN, set cooloff; if already cooling off, set HALT.
      Also count WARNs over the last 300s; if repeats >= halt_repeats, set HALT.

    - enforce(): returns (allow: bool, reason: str|None) based on state.
    - ops: cooloff(sec), reset(), arm(), disarm().
    """

    def __init__(
        self,
        *,
        threshold_ms: float = 30.0,
        window_sec: int = 60,
        base_cooloff_sec: int = 120,
        halt_threshold_repeats: int = 2,
    ) -> None:
        self.threshold_ms = float(threshold_ms)
        self.window_sec = int(window_sec)
        self.base_cooloff_sec = int(base_cooloff_sec)
        self.halt_threshold_repeats = int(halt_threshold_repeats)

        self._samples: deque[tuple[float, float]] = deque()  # (ts, latency_ms)
        self._warn_ts: deque[float] = deque()
        self.state = GuardState()

    def _now(self) -> float:
        return time.time()

    def record(self, latency_ms: float, now: float | None = None) -> tuple[bool, float]:
        now = self._now() if now is None else float(now)
        self._samples.append((now, float(latency_ms)))
        # evict old
        cutoff = now - self.window_sec
        while self._samples and self._samples[0][0] < cutoff:
            self._samples.popleft()
        # compute p95
        if not self._samples:
            return True, 0.0
        arr = np.array([x[1] for x in self._samples], dtype=float)
        p95 = float(np.percentile(arr, 95))
        if p95 > self.threshold_ms:
            self._register_warn(now)
        return p95 <= self.threshold_ms, p95

    def _register_warn(self, now: float) -> None:
        # track recent warns (last 300s)
        self._warn_ts.append(now)
        cutoff = now - 300.0
        while self._warn_ts and self._warn_ts[0] < cutoff:
            self._warn_ts.popleft()

        # If already cooling off, escalate to halt
        if self.in_cooloff(now):
            self.state.halted = True
        else:
            # start cooloff
            self.state.cooloff_until = max(self.state.cooloff_until, now + self.base_cooloff_sec)

        # Halt if too many warns in horizon
        if len(self._warn_ts) >= self.halt_threshold_repeats:
            self.state.halted = True

    def in_cooloff(self, now: float | None = None) -> bool:
        now = self._now() if now is None else float(now)
        return now < self.state.cooloff_until

    def enforce(self, now: float | None = None) -> tuple[bool, str | None]:
        now = self._now() if now is None else float(now)
        if not self.state.armed:
            return False, "disarmed"
        if self.state.halted:
            return False, "halt"
        if self.in_cooloff(now):
            return False, "cooloff"
        return True, None

    # --- OPS ---
    def cooloff(self, sec: int, now: float | None = None) -> float:
        now = self._now() if now is None else float(now)
        until = now + max(0, int(sec))
        self.state.cooloff_until = max(self.state.cooloff_until, until)
        return self.state.cooloff_until

    def reset(self) -> None:
        self._warn_ts.clear()
        self.state.cooloff_until = 0.0
        self.state.halted = False

    def arm(self) -> None:
        self.state.armed = True

    def disarm(self) -> None:
        self.state.armed = False

    def snapshot(self) -> dict:
        return {
            "armed": self.state.armed,
            "cooloff_until": self.state.cooloff_until,
            "halted": self.state.halted,
            "samples": len(self._samples),
            "warns_5m": len(self._warn_ts),
            "threshold_ms": self.threshold_ms,
            "window_sec": self.window_sec,
            "base_cooloff_sec": self.base_cooloff_sec,
            "halt_threshold_repeats": self.halt_threshold_repeats,
        }
