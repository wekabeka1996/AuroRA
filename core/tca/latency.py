from __future__ import annotations

"""
TCA — Latency economics and SLA gate
====================================

Mathematical framing
--------------------
Let E_bps be the expected pre-trade edge (in basis points). Let L_ms be the
realized decision→exchange latency in milliseconds. Assume latency leak rate κ
(in bps per ms). The expected post-latency edge is

    E_after = E_bps - κ * L_ms .

Additionally, if latency breaches the Service Level Agreement (SLA), we can
hard-deny the order. This module provides tiny utilities to compute these
quantities and a simple SLA gate that can be embedded into a router.

Notes
-----
- Pure Python; integrates with SSOT-config if available (execution.sla.*)
- κ can be estimated offline by regressing realized slippage (bps) on latency
  (ms) conditional on venue/instrument and clock bucket.
"""

from dataclasses import dataclass
from typing import Optional

from core.config.loader import get_config, ConfigError


def edge_after_latency(edge_bps: float, latency_ms: float, kappa_bps_per_ms: float) -> float:
    """Return expected post-latency edge in bps.

    E_after = edge_bps - kappa * latency_ms
    """
    e = float(edge_bps) - float(kappa_bps_per_ms) * float(latency_ms)
    return e


def implied_kappa_bps_per_ms(edge_bps_before: float, edge_bps_after: float, latency_ms: float) -> float:
    """Infer κ from a single observation (for diagnostics only)."""
    if latency_ms == 0:
        return 0.0
    return (float(edge_bps_before) - float(edge_bps_after)) / float(latency_ms)


@dataclass
class SLAGateResult:
    allow: bool
    reason: str
    edge_after_bps: float
    latency_ms: float
    max_latency_ms: float


class SLAGate:
    """SLA gate for maker/taker routing decisions.

    Parameters
    ----------
    max_latency_ms : deny orders if measured latency exceeds this bound
    kappa_bps_per_ms : leak rate that converts measured latency to expected edge loss
    min_edge_after_bps : deny if post-latency edge < this floor
    """

    def __init__(
        self,
        *,
        max_latency_ms: Optional[float] = None,
        kappa_bps_per_ms: float = 0.05,
        min_edge_after_bps: float = 0.0,
    ) -> None:
        # Load defaults from SSOT-config if present
        if max_latency_ms is None:
            try:
                cfg = get_config()
                max_latency_ms = float(cfg.get("execution.sla.max_latency_ms", 25))
            except (ConfigError, Exception):
                max_latency_ms = 25.0
        self.max_latency_ms = float(max_latency_ms)
        self.kappa = float(kappa_bps_per_ms)
        self.min_edge_after_bps = float(min_edge_after_bps)

    def gate(self, *, edge_bps: float, latency_ms: float) -> SLAGateResult:
        # Hard SLA cap
        L = float(latency_ms)
        if L > self.max_latency_ms:
            return SLAGateResult(
                allow=False,
                reason=f"SLA: latency {L:.2f}ms > max {self.max_latency_ms:.2f}ms",
                edge_after_bps=edge_after_latency(edge_bps, L, self.kappa),
                latency_ms=L,
                max_latency_ms=self.max_latency_ms,
            )
        # Convert to post-latency edge
        e_after = edge_after_latency(edge_bps, L, self.kappa)
        if e_after < self.min_edge_after_bps:
            return SLAGateResult(
                allow=False,
                reason=f"Edge after latency {e_after:.2f}bps < floor {self.min_edge_after_bps:.2f}bps",
                edge_after_bps=e_after,
                latency_ms=L,
                max_latency_ms=self.max_latency_ms,
            )
        return SLAGateResult(
            allow=True,
            reason="OK",
            edge_after_bps=e_after,
            latency_ms=L,
            max_latency_ms=self.max_latency_ms,
        )


__all__ = ["edge_after_latency", "implied_kappa_bps_per_ms", "SLAGate", "SLAGateResult"]
