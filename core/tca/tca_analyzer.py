from __future__ import annotations

"""
TCA — Transaction Cost Analysis v1.0
====================================

Comprehensive transaction cost analysis with:
- Implementation shortfall calculation
- Spread cost decomposition
- Latency slippage measurement
- Adverse selection detection
- Temporary impact estimation
- Multi-timeframe aggregation
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime
import time
import statistics


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


@dataclass
class TCAMetrics:
    """Comprehensive TCA metrics for an order"""
    # Core shortfall metrics
    implementation_shortfall_bps: float
    spread_cost_bps: float
    latency_slippage_bps: float
    adverse_selection_bps: float
    temporary_impact_bps: float
    
    # Price references
    arrival_price: float
    vwap_fill: float
    mid_at_decision: float
    mid_at_first_fill: float
    mid_at_last_fill: float
    
    # Timing metrics
    decision_latency_ms: float
    time_to_first_fill_ms: float
    total_execution_time_ms: float
    arrival_ts_ns: int  # Add this for time window aggregation
    
    # Fill quality metrics
    fill_ratio: float
    maker_fill_ratio: float
    taker_fill_ratio: float
    avg_queue_position: Optional[float]
    
    # Cost metrics
    total_fees: float
    fees_bps: float
    
    # Market impact metrics
    realized_spread_bps: float
    effective_spread_bps: float
    
    # Metadata
    symbol: str
    side: str
    order_id: str
    analysis_ts_ns: int


class TCAAnalyzer:
    """Transaction Cost Analysis engine v1.0"""
    
    def __init__(self, adverse_window_s: float = 1.0, mark_ref: str = "micro"):
        self.adverse_window_s = adverse_window_s
        self.mark_ref = mark_ref  # "mid" or "micro"
        
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
        
        # For spread cost, always use mid price (not micro)
        mid_for_spread = market_data.get('mid_price', 100.0)
        
        # Calculate core TCA metrics
        impl_shortfall_bps = self._calculate_implementation_shortfall(
            side_sign, arrival_price, vwap_fill, execution.total_fees, execution.total_filled_qty
        )
        
        spread_cost_bps = self._calculate_spread_cost(
            side_sign, vwap_fill, mid_for_spread
        )
        
        latency_slippage_bps = self._calculate_latency_slippage(
            side_sign, mid_decision, mid_first_fill
        )
        
        adverse_selection_bps = self._calculate_adverse_selection(
            execution, market_data, side_sign
        )
        
        temporary_impact_bps = self._calculate_temporary_impact(
            impl_shortfall_bps, spread_cost_bps, latency_slippage_bps, adverse_selection_bps
        )
        
        # Fill quality metrics
        maker_fills = [f for f in execution.fills if f.liquidity_flag == 'M']
        taker_fills = [f for f in execution.fills if f.liquidity_flag == 'T']
        
        maker_fill_ratio = sum(f.qty for f in maker_fills) / execution.total_filled_qty if execution.fills else 0.0
        taker_fill_ratio = sum(f.qty for f in taker_fills) / execution.total_filled_qty if execution.fills else 0.0
        
        # Calculate average queue position (only if positions are available)
        queue_positions = [f.queue_pos for f in execution.fills if f.queue_pos is not None]
        avg_queue_pos = statistics.mean(queue_positions) if queue_positions else None
        
        # Cost metrics
        fees_bps = execution.total_fees * 1e4 / (execution.total_filled_qty * arrival_price) if execution.total_filled_qty > 0 else 0.0
        
        # Market impact metrics
        realized_spread_bps = self._calculate_realized_spread(side_sign, vwap_fill, mid_last_fill)
        effective_spread_bps = self._calculate_effective_spread(side_sign, vwap_fill, mid_decision)
        
        # Timing metrics
        time_to_first_fill = (execution.fills[0].ts_ns - execution.decision_ts_ns) / 1e6 if execution.fills else 0.0
        total_execution_time = execution.execution_time_ns / 1e6
        
        return TCAMetrics(
            implementation_shortfall_bps=impl_shortfall_bps,
            spread_cost_bps=spread_cost_bps,
            latency_slippage_bps=latency_slippage_bps,
            adverse_selection_bps=adverse_selection_bps,
            temporary_impact_bps=temporary_impact_bps,
            arrival_price=arrival_price,
            vwap_fill=vwap_fill,
            mid_at_decision=mid_decision,
            mid_at_first_fill=mid_first_fill,
            mid_at_last_fill=mid_last_fill,
            decision_latency_ms=execution.latency_ms,
            time_to_first_fill_ms=time_to_first_fill,
            total_execution_time_ms=total_execution_time,
            fill_ratio=execution.fill_ratio,
            maker_fill_ratio=maker_fill_ratio,
            taker_fill_ratio=taker_fill_ratio,
            avg_queue_position=avg_queue_pos,
            total_fees=execution.total_fees,
            fees_bps=fees_bps,
            realized_spread_bps=realized_spread_bps,
            effective_spread_bps=effective_spread_bps,
            symbol=execution.symbol,
            side=execution.side,
            order_id=execution.order_id,
            arrival_ts_ns=execution.arrival_ts_ns,  # Add this
            analysis_ts_ns=int(time.time_ns())
        )
    
    def _calculate_implementation_shortfall(
        self, side_sign: float, arrival_price: float, vwap_fill: float, fees: float, filled_qty: float
    ) -> float:
        """Calculate implementation shortfall in bps"""
        if arrival_price <= 0 or filled_qty <= 0:
            return 0.0
        
        # IS calculation with mirror symmetry for buy/sell
        if side_sign > 0:  # BUY
            price_diff = (vwap_fill - arrival_price) / arrival_price
        else:  # SELL
            price_diff = - (arrival_price - vwap_fill) / arrival_price  # Make SELL negative for symmetry
        
        fees_bps = fees * 1e4 / (filled_qty * arrival_price)
        
        return (price_diff * 1e4) + fees_bps
    
    def _calculate_spread_cost(self, side_sign: float, vwap_fill: float, mid_price: float) -> float:
        """Calculate spread cost in bps"""
        if mid_price <= 0:
            return 0.0
        
        # Spread cost = side * (P_fill - P_mid) / P_mid * 1e4
        return side_sign * (vwap_fill - mid_price) / mid_price * 1e4
    
    def _calculate_latency_slippage(self, side_sign: float, mid_decision: float, mid_first_fill: float) -> float:
        """Calculate latency slippage in bps"""
        if mid_decision <= 0:
            return 0.0
        
        # Latency slippage = side * (P_mid_at_fill - P_mid_at_decision) / P_mid_at_decision * 1e4
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
        
        # Adverse selection = side * (P_mid_adverse - P_mid_at_fill) / P_mid_at_fill * 1e4
        return side_sign * (mid_adverse - mid_at_fill) / mid_at_fill * 1e4
    
    def _calculate_temporary_impact(self, is_bps: float, spread_bps: float, latency_bps: float, adverse_bps: float) -> float:
        """Calculate temporary market impact"""
        # Temporary impact = IS - Spread - Latency - Adverse
        return is_bps - spread_bps - latency_bps - adverse_bps
    
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
        # This is a placeholder - in real implementation, this would query
        # the market data store for the best bid/ask at the given timestamp
        # For now, return a dummy implementation based on mark_ref setting
        if self.mark_ref == "micro":
            return market_data.get('micro_price', market_data.get('mid_price', 100.0))
        else:  # "mid"
            return market_data.get('mid_price', 100.0)
    
    def aggregate_metrics(
        self, 
        metrics_list: List[TCAMetrics], 
        group_by: str = "symbol",
        time_window_s: int = 300
    ) -> Dict[str, Dict[str, float]]:
        """Aggregate TCA metrics by symbol/time window"""
        if not metrics_list:
            return {}
        
        # Group metrics
        groups = {}
        for metric in metrics_list:
            if group_by == "symbol":
                key = metric.symbol
            else:
                # Group by time window
                window_start = (metric.arrival_ts_ns // (time_window_s * 1e9)) * time_window_s
                key = f"{metric.symbol}_{window_start}"
            
            if key not in groups:
                groups[key] = []
            groups[key].append(metric)
        
        # Calculate aggregates
        aggregates = {}
        for key, group_metrics in groups.items():
            aggregates[key] = {
                'avg_implementation_shortfall_bps': statistics.mean([m.implementation_shortfall_bps for m in group_metrics]),
                'avg_spread_cost_bps': statistics.mean([m.spread_cost_bps for m in group_metrics]),
                'avg_latency_slippage_bps': statistics.mean([m.latency_slippage_bps for m in group_metrics]),
                'avg_adverse_selection_bps': statistics.mean([m.adverse_selection_bps for m in group_metrics]),
                'avg_temporary_impact_bps': statistics.mean([m.temporary_impact_bps for m in group_metrics]),
                'avg_fill_ratio': statistics.mean([m.fill_ratio for m in group_metrics]),
                'avg_fees_bps': statistics.mean([m.fees_bps for m in group_metrics]),
                'p50_implementation_shortfall_bps': statistics.median([m.implementation_shortfall_bps for m in group_metrics]),
                'p90_implementation_shortfall_bps': statistics.quantiles([m.implementation_shortfall_bps for m in group_metrics], n=10)[8] if len(group_metrics) >= 10 else statistics.mean([m.implementation_shortfall_bps for m in group_metrics]),
                'total_orders': len(group_metrics),
                'total_volume': sum([m.fill_ratio * 1000 for m in group_metrics])  # Approximate volume
            }
        
        return aggregates


__all__ = ["FillEvent", "OrderExecution", "TCAMetrics", "TCAAnalyzer"]