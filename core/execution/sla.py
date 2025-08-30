from __future__ import annotations

"""
Execution — SLA monitor and gate
================================

Production-grade SLA enforcement for routing decisions, built on top of the
TCA latency economics. Provides a rolling latency monitor (percentiles) and a
single-call gating interface that converts latency to post-latency edge and
applies hard SLA cutoffs.

Key formulas
------------
Let E_bps be the pre-trade expected edge (basis points), L_ms be measured
latency, and κ be leak rate (bps/ms). Then expected edge **after** latency is

    E_after = E_bps - κ L_ms.

The SLA gate denies if (i) L_ms > max_latency_ms or (ii) E_after < edge_floor.

Integration
-----------
- Default thresholds are read from SSOT-config (`execution.sla.max_latency_ms`).
- κ can be calibrated offline; a conservative default is used here.
- Designed to be called by `execution/router.py`.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional, Tuple
from pathlib import Path

from core.tca.latency import SLAGate, SLAGateResult
from core.config.loader import get_config, ConfigError


NS_PER_MS = 1_000_000


@dataclass
class SLASummary:
    count: int
    p50_ms: float
    p90_ms: float
    p99_ms: float


class _Quantile:
    """Simple deterministic quantile estimator on a bounded window.

    Keeps a deque of last N latencies and computes exact order statistics on
    demand. For production, this can be replaced with a CKMS or t-digest, but
    deterministic exact ranks help tests and reproducibility.
    """

    def __init__(self, limit: int = 10_000) -> None:
        self._dq: Deque[float] = deque(maxlen=int(limit))

    def push(self, x_ms: float) -> None:
        self._dq.append(float(x_ms))

    def quantile(self, q: float) -> float:
        arr = sorted(self._dq)
        if not arr:
            return 0.0
        q = 0.0 if q < 0.0 else 1.0 if q > 1.0 else q
        pos = q * (len(arr) - 1)
        lo = int(pos)
        hi = min(lo + 1, len(arr) - 1)
        frac = pos - lo
        return arr[lo] * (1 - frac) + arr[hi] * frac

    def summary(self) -> SLASummary:
        n = len(self._dq)
        return SLASummary(
            count=n,
            p50_ms=self.quantile(0.5),
            p90_ms=self.quantile(0.9),
            p99_ms=self.quantile(0.99),
        )


class SLAMonitor:
    """Rolling SLA monitor and gate wrapper.

    Example
    -------
    sla = SLAMonitor(kappa_bps_per_ms=0.05, edge_floor_bps=0.0)
    # record observed latencies
    sla.observe(12.3)
    # check an order
    res = sla.check(edge_bps=8.0, latency_ms=15.0)
    if not res.allow: ...
    print(sla.summary())
    """

    def __init__(
        self,
        *,
        window: int = 10_000,
        kappa_bps_per_ms: float = 0.05,
        edge_floor_bps: float = 0.0,
        max_latency_ms: Optional[float] = None,
    ) -> None:
        self._q = _Quantile(limit=window)
        if max_latency_ms is None:
            try:
                cfg = get_config()
                max_latency_ms = float(cfg.get("execution.sla.max_latency_ms", 25))
            except (ConfigError, Exception):
                max_latency_ms = 25.0
        self._gate = SLAGate(
            max_latency_ms=float(max_latency_ms),
            kappa_bps_per_ms=float(kappa_bps_per_ms),
            min_edge_after_bps=float(edge_floor_bps),
        )

    # ---- monitoring ----

    def observe(self, latency_ms: float) -> None:
        self._q.push(float(latency_ms))

    def summary(self) -> SLASummary:
        return self._q.summary()

    # ---- gating ----

    def check(self, *, edge_bps: float, latency_ms: float) -> SLAGateResult:
        """Apply SLA gate to a decision. Also records latency for monitoring."""
        self.observe(latency_ms)
        result = self._gate.gate(edge_bps=edge_bps, latency_ms=latency_ms)
        
        # XAI logging (use a simple approach without validation)
        why_code = "OK" if result.allow else (
            "WHY_LATENCY_BREACH" if latency_ms > self._gate.max_latency_ms 
            else "WHY_EDGE_AFTER_LT_FLOOR"
        )
        
        # Log the SLA check (skip decision validation)
        log_entry = {
            "event_type": "SLA_CHECK",
            "timestamp_ns": 0,  # Would be set by logger
            "why_code": why_code,
            "inputs": {
                "edge_bps": edge_bps,
                "latency_ms": latency_ms,
                "kappa_bps_per_ms": self._gate.kappa,
                "max_latency_ms": self._gate.max_latency_ms,
                "edge_floor_bps": self._gate.min_edge_after_bps
            },
            "outputs": {
                "allow": result.allow,
                "edge_after_bps": result.edge_after_bps,
                "reason": result.reason
            }
        }
        
        # Simple file logging for SLA events
        import json
        log_path = Path("logs/sla_decisions.jsonl")
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, separators=(",", ":")) + "\n")
        
        return result


__all__ = ["SLAMonitor", "SLASummary"]
