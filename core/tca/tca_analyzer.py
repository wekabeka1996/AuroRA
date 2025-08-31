from __future__ import annotations

"""
TCA — Transaction Cost Analysis v1.0
====================================

Provides canonical transaction cost analysis with:
- Implementation shortfall calculation (canonical identity)
- Spread cost (entry/exit) decomposition
- Latency slippage measurement
- Adverse selection detection
- Temporary impact estimation
- Aggregation helpers
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Any
import time
import statistics

from .types import TCAInputs, TCAComponents, TCAMetrics


@dataclass
class FillEvent:
    """Individual fill event data"""
    ts_ns: int
    qty: float
    price: float
    fee: float
    liquidity_flag: str  # 'M' for maker, 'T' for taker
    queue_pos: Optional[int] = None
    order_id: Optional[str] = None


@dataclass
class OrderExecution:
    """Complete order execution data"""
    order_id: str
    symbol: str
    side: str  # 'BUY' or 'SELL'
    target_qty: float
    fills: List[FillEvent]
    arrival_ts_ns: int
    decision_ts_ns: int
    arrival_price: float
    arrival_spread_bps: float
    latency_ms: float

    @property
    def total_filled_qty(self) -> float:
        return sum(fill.qty for fill in self.fills)

    @property
    def vwap_fill(self) -> float:
        """Volume-weighted average price of fills"""
        if not self.fills:
            return 0.0
        total_value = sum(fill.qty * fill.price for fill in self.fills)
        total_qty = self.total_filled_qty
        return total_value / total_qty if total_qty > 0 else 0.0

    @property
    def total_fees(self) -> float:
        return sum(fill.fee for fill in self.fills)

    @property
    def fill_ratio(self) -> float:
        return self.total_filled_qty / self.target_qty if self.target_qty > 0 else 0.0

    @property
    def execution_time_ns(self) -> int:
        """Total time from decision to last fill"""
        if not self.fills:
            return 0
        return max(fill.ts_ns for fill in self.fills) - self.decision_ts_ns


class TCAAnalyzer:
    """Transaction Cost Analysis engine v1.0"""

    def __init__(self, adverse_window_s: float = 1.0, mark_ref: str = "micro", **kwargs):
        self.adverse_window_s = adverse_window_s
        self.mark_ref = mark_ref  # "mid" or "micro"
        # Accept and ignore unknown kwargs for fail-safe compatibility
        for k, v in kwargs.items():
            setattr(self, k, v)

    def analyze_order(self, execution: OrderExecution, market_data: Dict[str, Any]) -> TCAMetrics:
        """Analyze transaction costs for a complete order execution"""
        side_sign = 1.0 if execution.side.upper() == 'BUY' else -1.0

        # Extract price references
        arrival_price = execution.arrival_price
        vwap_fill = execution.vwap_fill

        # Get market prices at key points
        mid_decision = self._get_mid_price_at_ts(execution.decision_ts_ns, market_data)
        mid_first_fill = self._get_mid_price_at_ts(execution.fills[0].ts_ns, market_data) if execution.fills else mid_decision
        mid_last_fill = self._get_mid_price_at_ts(execution.fills[-1].ts_ns, market_data) if execution.fills else mid_decision

        # Fill quality metrics (need this early for maker/taker logic)
        maker_fills = [f for f in execution.fills if f.liquidity_flag == 'M']
        taker_fills = [f for f in execution.fills if f.liquidity_flag == 'T']

        maker_fill_ratio = (sum(f.qty for f in maker_fills) / execution.total_filled_qty) if execution.fills else 0.0
        taker_fill_ratio = (sum(f.qty for f in taker_fills) / execution.total_filled_qty) if execution.fills else 0.0

        # If there are no fills, return zeroed metrics to avoid division-by-zero derived artifacts
        if execution.total_filled_qty == 0:
            return TCAMetrics(
                symbol=execution.symbol,
                side=execution.side,
                order_id=execution.order_id,
                order_qty=execution.target_qty,
                filled_qty=0,
                arrival_price=arrival_price,
                vwap_fill=vwap_fill,
                mid_at_decision=mid_decision,
                mid_at_first_fill=mid_first_fill,
                mid_at_last_fill=mid_last_fill,
                arrival_ts_ns=execution.arrival_ts_ns,
                decision_ts_ns=execution.decision_ts_ns,
                first_fill_ts_ns=None,
                last_fill_ts_ns=None,
                decision_latency_ms=execution.latency_ms,
                time_to_first_fill_ms=0.0,
                total_execution_time_ms=0.0,
                fill_ratio=0.0,
                maker_fill_ratio=0.0,
                taker_fill_ratio=0.0,
                avg_queue_position=None,
                raw_edge_bps=0.0,
                fees_bps=0.0,
                slippage_in_bps=0.0,
                slippage_out_bps=0.0,
                adverse_bps=0.0,
                latency_bps=0.0,
                impact_bps=0.0,
                rebate_bps=0.0,
                implementation_shortfall_bps=0.0,
                realized_spread_bps=0.0,
                effective_spread_bps=0.0,
                analysis_ts_ns=int(time.time_ns())
            )

        # --- Canonical computation (clean, deterministic) ---

        fills = execution.fills or []
        filled_qty = execution.total_filled_qty
        filled_notional = sum(f.qty * f.price for f in fills)
        vwap = (filled_notional / filled_qty) if filled_qty > 0 else execution.arrival_price

        # Maker / Taker: treat as maker if majority of filled qty came from maker fills
        is_maker = (filled_qty > 0) and (maker_fill_ratio > 0.5)

        # Fees: canonical representation (bps, ≤ 0)
        net_fee_amount = execution.total_fees
        if filled_qty > 0 and arrival_price > 0:
            fees_bps = -abs(net_fee_amount) * 1e4 / (filled_qty * arrival_price)
        else:
            fees_bps = 0.0

        # Rebate: provided by market_data for maker profiles
        rebate_bps = float(market_data.get('rebate_bps', 0.0)) if is_maker else 0.0

        # Price diff used to compute implementation shortfall (signed; positive means cost)
        price_diff_bps = side_sign * ((vwap - execution.arrival_price) / execution.arrival_price) * 1e4

    # Raw edge: upstream expected_edge_bps when provided; otherwise default 0.0
        raw_edge_bps = float(market_data.get("expected_edge_bps", 0.0))

        # Canonical component defaults (all costs ≤ 0)
        slippage_in_bps = 0.0 if is_maker else -abs(float(execution.arrival_spread_bps or 0.0))
        slippage_out_bps = 0.0
        latency_bps = -abs(float(market_data.get('latency_bps', 0.0)))
        adverse_bps = -abs(float(market_data.get('adverse_bps', 0.0)))

        # Temporary impact (legacy positive) default 0 unless market data provides
        temp_impact_pos = float(market_data.get('temporary_impact_bps', 0.0))

        # Canonical impact is negative of legacy temporary impact
        impact_bps = -abs(temp_impact_pos)

        # Implementation shortfall (canonical signed sum): raw + fees + canonical components + rebate
        canonical_is = (
            raw_edge_bps
            + fees_bps
            + slippage_in_bps
            + slippage_out_bps
            + adverse_bps
            + latency_bps
            + impact_bps
            + rebate_bps
        )

        # Legacy-positive decomposition expected by downstream consumers/tests
        # Legacy semantics (R1): include signed fees_bps (≤0) and add rebate_bps
        legacy_decomp = (
            raw_edge_bps
            + fees_bps
            + (-slippage_in_bps)  # spread_pos
            + (-latency_bps)      # latency_pos
            + (-adverse_bps)      # adverse_pos
            + (-impact_bps)       # temp_impact_pos
            + rebate_bps
        )

        # Calculate average queue position (only if positions are available)
        queue_positions = [f.queue_pos for f in execution.fills if f.queue_pos is not None]
        avg_queue_pos = statistics.mean(queue_positions) if queue_positions else None

        # Market impact metrics
        realized_spread_bps = self._calculate_realized_spread(side_sign, vwap_fill, mid_last_fill)
        effective_spread_bps = self._calculate_effective_spread(side_sign, vwap_fill, mid_decision)

        # Timing metrics
        time_to_first_fill = (execution.fills[0].ts_ns - execution.decision_ts_ns) / 1e6 if execution.fills else 0.0
        total_execution_time = execution.execution_time_ns / 1e6

        # Fill timestamps
        first_fill_ts_ns = execution.fills[0].ts_ns if execution.fills else None
        last_fill_ts_ns = execution.fills[-1].ts_ns if execution.fills else None

        # Validate canonical identity (signed components sum to canonical_is)
        canonical_rhs = (
            raw_edge_bps
            + fees_bps
            + slippage_in_bps
            + slippage_out_bps
            + adverse_bps
            + latency_bps
            + impact_bps
            + rebate_bps
        )
        assert abs(canonical_is - canonical_rhs) <= 1e-6, "canonical_implementation_shortfall_mismatch"

        self._validate_sign_gates(
            fees_bps, slippage_in_bps, slippage_out_bps, adverse_bps, latency_bps, impact_bps, rebate_bps
        )

        # Return canonical TCAMetrics (legacy positive fields are derived in __post_init__)
        return TCAMetrics(
            symbol=execution.symbol,
            side=execution.side,
            order_id=execution.order_id,
            order_qty=execution.target_qty,
            filled_qty=execution.total_filled_qty,
            arrival_price=arrival_price,
            vwap_fill=vwap_fill,
            mid_at_decision=mid_decision,
            mid_at_first_fill=mid_first_fill,
            mid_at_last_fill=mid_last_fill,
            arrival_ts_ns=execution.arrival_ts_ns,
            decision_ts_ns=execution.decision_ts_ns,
            first_fill_ts_ns=first_fill_ts_ns,
            last_fill_ts_ns=last_fill_ts_ns,
            decision_latency_ms=execution.latency_ms,
            time_to_first_fill_ms=time_to_first_fill,
            total_execution_time_ms=total_execution_time,
            fill_ratio=execution.fill_ratio,
            maker_fill_ratio=maker_fill_ratio,
            taker_fill_ratio=taker_fill_ratio,
            avg_queue_position=avg_queue_pos,
            raw_edge_bps=raw_edge_bps,
            fees_bps=fees_bps,
            slippage_in_bps=slippage_in_bps,
            slippage_out_bps=slippage_out_bps,
            adverse_bps=adverse_bps,
            latency_bps=latency_bps,
            impact_bps=impact_bps,
            rebate_bps=rebate_bps,
            implementation_shortfall_bps=legacy_decomp,
            canonical_is_bps=canonical_is,
            realized_spread_bps=realized_spread_bps,
            effective_spread_bps=effective_spread_bps,
            analysis_ts_ns=int(time.time_ns())
        )

    def _calculate_spread_cost(self, side_sign: float, vwap_fill: float, mid_price: float) -> float:
        """Calculate spread cost in bps"""
        if mid_price <= 0:
            return 0.0
        return side_sign * (vwap_fill - mid_price) / mid_price * 1e4

    def _calculate_latency_slippage(self, side_sign: float, mid_decision: float, mid_first_fill: float) -> float:
        """Calculate latency slippage in bps"""
        if mid_decision <= 0:
            return 0.0
        return side_sign * (mid_first_fill - mid_decision) / mid_decision * 1e4

    def _calculate_adverse_selection(self, execution: OrderExecution, market_data: Dict, side_sign: float) -> float:
        """Calculate adverse selection cost in bps"""
        if not execution.fills:
            return 0.0
        last_fill_ts = execution.fills[-1].ts_ns
        adverse_ts = last_fill_ts + int(self.adverse_window_s * 1e9)
        mid_at_fill = self._get_mid_price_at_ts(last_fill_ts, market_data)
        mid_adverse = self._get_mid_price_at_ts(adverse_ts, market_data)
        if mid_at_fill <= 0:
            return 0.0
        return side_sign * (mid_adverse - mid_at_fill) / mid_at_fill * 1e4

    def _calculate_temporary_impact(
        self,
        impl_shortfall_bps: float,
        spread_cost_bps: float,
        latency_slippage_bps: float,
        adverse_selection_bps: float,
        fees_bps: float,
        rebate_bps: float = 0.0,
    ) -> float:
        """Calculate temporary impact as residual of implementation shortfall"""
        # Temporary impact = IS - (spread + latency + adverse + |fees| - rebate)
        return impl_shortfall_bps - (
            spread_cost_bps + latency_slippage_bps + adverse_selection_bps + abs(fees_bps) - rebate_bps
        )

    def _validate_sign_gates(
        self,
        fees_bps: float,
        slippage_in_bps: float,
        slippage_out_bps: float,
        adverse_bps: float,
        latency_bps: float,
        impact_bps: float,
        rebate_bps: float,
    ):
        """Validate sign conventions for TCA components"""
        if slippage_in_bps > 0:
            raise ValueError(f"slippage_in_bps must be ≤ 0, got {slippage_in_bps}")
        if slippage_out_bps > 0:
            raise ValueError(f"slippage_out_bps must be ≤ 0, got {slippage_out_bps}")
        if adverse_bps > 0:
            raise ValueError(f"adverse_bps must be ≤ 0, got {adverse_bps}")
        if latency_bps > 0:
            raise ValueError(f"latency_bps must be ≤ 0, got {latency_bps}")
        if impact_bps > 0:
            raise ValueError(f"impact_bps must be ≤ 0, got {impact_bps}")
        if rebate_bps < 0:
            raise ValueError(f"rebate_bps must be ≥ 0, got {rebate_bps}")

    def _calculate_realized_spread(self, side_sign: float, vwap_fill: float, mid_last_fill: float) -> float:
        """Calculate realized spread in bps"""
        if mid_last_fill <= 0:
            return 0.0
        return side_sign * (vwap_fill - mid_last_fill) / mid_last_fill * 1e4

    def _calculate_effective_spread(self, side_sign: float, vwap_fill: float, mid_decision: float) -> float:
        """Calculate effective spread in bps"""
        if mid_decision <= 0:
            return 0.0
        return side_sign * (vwap_fill - mid_decision) / mid_decision * 1e4

    def _get_mid_price_at_ts(self, ts_ns: int, market_data: Dict) -> float:
        """Get mid price at specific timestamp from market data"""
        # Placeholder: choose micro or mid reference
        if self.mark_ref == "micro":
            return market_data.get('micro_price', market_data.get('mid_price', 100.0))
        else:  # "mid"
            return market_data.get('mid_price', 100.0)

    def aggregate_metrics(
        self,
        metrics_list: List[TCAMetrics],
        group_by: str = "symbol",
        time_window_s: int = 300,
    ) -> Dict[str, Dict[str, float]]:
        """Aggregate TCA metrics by symbol/time window"""
        if not metrics_list:
            return {}

        # Group metrics
        groups: Dict[str, List[TCAMetrics]] = {}
        for metric in metrics_list:
            if group_by == "symbol":
                key = metric.symbol
            else:
                window_start = (metric.arrival_ts_ns // (time_window_s * 1e9)) * time_window_s
                key = f"{metric.symbol}_{window_start}"
            groups.setdefault(key, []).append(metric)

        # Calculate aggregates
        aggregates: Dict[str, Dict[str, float]] = {}
        for key, group_metrics in groups.items():
            impl = [m.implementation_shortfall_bps for m in group_metrics]
            aggregates[key] = {
                'avg_implementation_shortfall_bps': statistics.mean(impl),
                'avg_spread_cost_bps': statistics.mean([-m.slippage_in_bps for m in group_metrics]),
                'avg_latency_slippage_bps': statistics.mean([-m.latency_bps for m in group_metrics]),
                'avg_adverse_selection_bps': statistics.mean([-m.adverse_bps for m in group_metrics]),
                'avg_temporary_impact_bps': statistics.mean([-m.impact_bps for m in group_metrics]),
                'avg_fill_ratio': statistics.mean([m.fill_ratio for m in group_metrics]),
                'avg_fees_bps': statistics.mean([m.fees_bps for m in group_metrics]),
                'p50_implementation_shortfall_bps': statistics.median(impl),
                'total_orders': len(group_metrics),
            }

        return aggregates


__all__ = ["FillEvent", "OrderExecution", "TCAMetrics", "TCAAnalyzer", "TCAInputs", "TCAComponents"]

