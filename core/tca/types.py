"""
TCA Types - Canonical Data Structures v1.0
==========================================

Canonical @dataclass definitions for TCA (Transaction Cost Analysis) components.
Provides unified interface with strict field definitions and sign conventions.

Sign Conventions (bps):
- fees_bps ≤ 0 (always negative or zero)
- slippage_in_bps ≤ 0 (taker: negative, maker: zero)
- slippage_out_bps ≤ 0 (exit slippage, always ≤ 0)
- adverse_bps ≤ 0 (always negative or zero)
- latency_bps ≤ 0 (always negative or zero)
- impact_bps ≤ 0 (always negative or zero)
- rebate_bps ≥ 0 (maker rebate, always positive or zero)

Identity: IS_bps = raw_edge_bps + fees_bps + slippage_in_bps + slippage_out_bps +
                   adverse_bps + latency_bps + impact_bps + rebate_bps
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, List
from datetime import datetime


@dataclass
class TCAInputs:
    """Canonical input parameters for TCA analysis"""
    symbol: str
    side: str  # 'BUY' or 'SELL'
    order_qty: float
    filled_qty: float
    vwap_fill: float
    arrival_price: float
    total_fees: float
    arrival_ts_ns: int
    decision_ts_ns: Optional[int] = None
    first_fill_ts_ns: Optional[int] = None
    last_fill_ts_ns: Optional[int] = None
    fill_ratio: float = 0.0
    maker_fill_ratio: float = 0.0
    taker_fill_ratio: float = 0.0
    fill_prob: float = 0.0  # [0,1] for maker profiles


@dataclass
class TCAComponents:
    """Canonical TCA cost components with strict sign conventions"""
    # Raw edge (PnL before costs)
    raw_edge_bps: float = 0.0

    # Cost components (all ≤ 0 except rebate_bps ≥ 0)
    fees_bps: float = 0.0          # ≤ 0
    slippage_in_bps: float = 0.0   # ≤ 0 (taker negative, maker zero)
    slippage_out_bps: float = 0.0  # ≤ 0 (exit slippage)
    adverse_bps: float = 0.0       # ≤ 0
    latency_bps: float = 0.0       # ≤ 0
    impact_bps: float = 0.0        # ≤ 0
    rebate_bps: float = 0.0        # ≥ 0 (maker only)

    # Implementation shortfall (sum of all components)
    implementation_shortfall_bps: float = 0.0

    # Metadata
    analysis_ts_ns: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1e9))


@dataclass
class TCAMetrics:
    """Canonical TCA metrics with complete field set"""
    # Core inputs
    symbol: str
    side: str
    order_id: str
    order_qty: float
    filled_qty: float

    # Price references
    arrival_price: float
    vwap_fill: float
    mid_at_decision: float
    mid_at_first_fill: float
    mid_at_last_fill: float

    # Timing
    arrival_ts_ns: int
    decision_ts_ns: Optional[int] = None
    first_fill_ts_ns: Optional[int] = None
    last_fill_ts_ns: Optional[int] = None
    decision_latency_ms: float = 0.0
    time_to_first_fill_ms: float = 0.0
    total_execution_time_ms: float = 0.0

    # Fill quality
    fill_ratio: float = 0.0
    maker_fill_ratio: float = 0.0
    taker_fill_ratio: float = 0.0
    avg_queue_position: Optional[float] = None

    # Cost components (canonical)
    raw_edge_bps: float = 0.0
    fees_bps: float = 0.0
    slippage_in_bps: float = 0.0
    slippage_out_bps: float = 0.0
    adverse_bps: float = 0.0
    latency_bps: float = 0.0
    impact_bps: float = 0.0
    rebate_bps: float = 0.0

    # Implementation shortfall
    implementation_shortfall_bps: float = 0.0
    # Canonical signed implementation shortfall (costs ≤0, rebate ≥0)
    canonical_is_bps: float = 0.0

    # Market impact
    realized_spread_bps: float = 0.0
    effective_spread_bps: float = 0.0

    # Metadata
    analysis_ts_ns: int = field(default_factory=lambda: int(datetime.now().timestamp() * 1e9))

    # Legacy fields for backward compatibility (mapped from canonical)
    spread_cost_bps: float = field(init=False)  # maps to slippage_in_bps
    latency_slippage_bps: float = field(init=False)  # maps to latency_bps
    adverse_selection_bps: float = field(init=False)  # maps to adverse_bps
    temporary_impact_bps: float = field(init=False)  # maps to impact_bps
    total_fees: float = field(init=False)  # computed from fees_bps
    slip_bps: float = field(init=False)  # maps to slippage_in_bps
    # Expose canonical components explicitly for clarity (defaults preserved)
    # raw_edge_bps, fees_bps, slippage_in_bps, slippage_out_bps, adverse_bps,
    # latency_bps, impact_bps, rebate_bps already present above

    def __post_init__(self):
        """Map canonical fields to legacy fields for backward compatibility"""
        # Legacy mappings
        # Convert canonical negative signs to legacy positive cost representations
        # e.g., canonical slippage_in_bps is ≤ 0, but legacy spread_cost_bps expected positive cost
        self.spread_cost_bps = -self.slippage_in_bps
        self.latency_slippage_bps = -self.latency_bps
        self.adverse_selection_bps = -self.adverse_bps
        self.temporary_impact_bps = -self.impact_bps
        self.slip_bps = -self.slippage_in_bps

        # Compute total_fees from fees_bps
        if self.filled_qty > 0 and self.arrival_price > 0:
            self.total_fees = abs(self.fees_bps) * self.filled_qty * self.arrival_price / 1e4
        else:
            self.total_fees = 0.0

        # Do NOT override implementation_shortfall_bps here; keep the canonical value
        # computed by the analyzer. We only provide legacy-positive field mappings
        # for backward compatibility (spread_cost_bps, temporary_impact_bps, etc.).

        # Ensure canonical_is_bps exists (may be set by analyzer)
        if not hasattr(self, 'canonical_is_bps'):
            self.canonical_is_bps = (
                self.raw_edge_bps
                + self.fees_bps
                + self.slippage_in_bps
                + self.slippage_out_bps
                + self.adverse_bps
                + self.latency_bps
                + self.impact_bps
                + self.rebate_bps
            )


__all__ = ["TCAInputs", "TCAComponents", "TCAMetrics"]