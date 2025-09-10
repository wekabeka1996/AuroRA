import warnings

warnings.warn(
    "core.execution.enhanced_router is archived; use core.execution.router_v2.RouterV2",
    DeprecationWarning,
    stacklevel=2,
)
from __future__ import annotations

"""
Execution — Enhanced Router v1.0
=================================

Advanced execution framework with:
- Maker→taker escalation with TTL
- Child order management and splitting
- Queue-aware re-peg logic
- Partial fill handling
- Cancel/replace orchestration
- Volatility spike guards
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Mapping, Optional, Tuple

from core.config.loader import ConfigError, get_config
from core.execution.exchange.common import Fees
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate


@dataclass
class QuoteSnapshot:
    bid_px: float
    ask_px: float
    bid_sz: float = 0.0
    ask_sz: float = 0.0
    ts_ns: int = 0
    spread_bps: float = 0.0

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid_px + self.ask_px)

    @property
    def half_spread_bps(self) -> float:
        if self.spread_bps > 0:
            return self.spread_bps * 0.5
        m = self.mid
        if m <= 0:
            return 0.0
        return (self.ask_px - self.bid_px) / m * 1e4 * 0.5


@dataclass
class ChildOrder:
    """Child order specification for splitting large orders"""

    qty: float
    price: float
    order_type: str  # 'maker' or 'taker'
    ttl_ms: int
    created_ts: int = 0

    def __post_init__(self):
        if self.created_ts == 0:
            self.created_ts = int(time.time() * 1000)


@dataclass
class ExecutionDecision:
    """Enhanced execution decision with child order management"""

    route: str  # 'maker' | 'taker' | 'deny'
    child_orders: List[ChildOrder]
    escalation_ttl_ms: int
    repeg_trigger_bps: float
    reason: str
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    net_e_maker_bps: float = 0.0
    net_e_taker_bps: float = 0.0
    vol_spike_detected: bool = False


class EnhancedRouter:
    """Enhanced execution router with advanced order management"""

    def __init__(
        self,
        *,
        hazard_model: Optional[CoxPH] = None,
        slagate: Optional[SLAGate] = None,
        min_p_fill: Optional[float] = None,
        fees: Optional[Fees] = None,
        exchange_name: str = "default",
    ) -> None:
        # Core components
        self._haz = hazard_model
        self._sla = slagate or self._create_default_sla()
        self._min_p = min_p_fill or 0.6
        self._fees = fees or Fees.from_exchange_config(exchange_name)

        # Load configuration
        self._cfg = self._load_config()

        # State tracking
        self._last_requote_ts: Dict[str, int] = {}
        self._requote_counts: Dict[str, int] = {}

    def _create_default_sla(self) -> SLAGate:
        """Create default SLA gate"""
        try:
            cfg = get_config()
            max_latency_ms = float(cfg.get("execution.sla.max_latency_ms", 25))
        except (ConfigError, Exception):
            max_latency_ms = 25.0
        return SLAGate(
            max_latency_ms=max_latency_ms, kappa_bps_per_ms=0.05, min_edge_after_bps=0.0
        )

    def _load_config(self) -> dict:
        """Load execution router configuration"""
        try:
            cfg = get_config()
            return {
                "mode_default": cfg.get("execution.router.mode_default", "hybrid"),
                "maker_offset_bps": cfg.get("execution.router.maker_offset_bps", 1.0),
                "taker_escalation_ttl_ms": cfg.get(
                    "execution.router.taker_escalation_ttl_ms", 1000
                ),
                "t_min_requote_ms": cfg.get("execution.router.t_min_requote_ms", 150),
                "max_requotes_per_min": cfg.get(
                    "execution.router.max_requotes_per_min", 20
                ),
                "post_only": cfg.get("execution.router.post_only", True),
                "ioc_cleanup": cfg.get("execution.router.ioc_cleanup", True),
                "spread_limit_bps": cfg.get("execution.router.spread_limit_bps", 80),
                "min_lot": cfg.get("execution.router.child_split.min_lot", 0.001),
                "max_children": cfg.get("execution.router.child_split.max_children", 5),
                "vol_spike_atr_mult": cfg.get(
                    "execution.router.vol_spike_guard.atr_mult", 2.0
                ),
                "vol_spike_window_s": cfg.get(
                    "execution.router.vol_spike_guard.window_s", 300
                ),
            }
        except (ConfigError, Exception):
            return self._default_config()

    def _default_config(self) -> dict:
        """Default configuration fallback"""
        return {
            "mode_default": "hybrid",
            "maker_offset_bps": 1.0,
            "taker_escalation_ttl_ms": 1000,
            "t_min_requote_ms": 150,
            "max_requotes_per_min": 20,
            "post_only": True,
            "ioc_cleanup": True,
            "spread_limit_bps": 80,
            "min_lot": 0.001,
            "max_children": 5,
            "vol_spike_atr_mult": 2.0,
            "vol_spike_window_s": 300,
        }

    def decide(
        self,
        *,
        symbol: str,
        side: str,
        target_qty: float,
        quote: QuoteSnapshot,
        edge_bps_estimate: float,
        latency_ms: float,
        fill_features: Optional[Mapping[str, float]] = None,
        current_atr: float = 0.0,
        position_age_sec: int = 0,
    ) -> ExecutionDecision:
        """Enhanced execution decision with child order management"""

        # Check volatility spike guard
        vol_spike = self._check_vol_spike(current_atr, quote.spread_bps)

        # Calculate expected edges
        e_maker, e_taker = self._calculate_expected_edges(
            side, quote, edge_bps_estimate, latency_ms, fill_features
        )

        # Determine routing mode
        route = self._determine_route(e_maker, e_taker, vol_spike)

        if route == "deny":
            return ExecutionDecision(
                route="deny",
                child_orders=[],
                escalation_ttl_ms=0,
                repeg_trigger_bps=0.0,
                reason="No attractive route or volatility spike",
                vol_spike_detected=vol_spike,
            )

        # Create child orders
        child_orders = self._create_child_orders(symbol, side, target_qty, route, quote)

        # Calculate escalation TTL
        escalation_ttl = self._cfg["taker_escalation_ttl_ms"] if route == "maker" else 0

        # Calculate re-peg trigger
        repeg_trigger = self._calculate_repeg_trigger(quote)

        return ExecutionDecision(
            route=route,
            child_orders=child_orders,
            escalation_ttl_ms=escalation_ttl,
            repeg_trigger_bps=repeg_trigger,
            reason=f"Route: {route}, children: {len(child_orders)}",
            maker_fee_bps=self._fees.maker_fee_bps,
            taker_fee_bps=self._fees.taker_fee_bps,
            net_e_maker_bps=e_maker,
            net_e_taker_bps=e_taker,
            vol_spike_detected=vol_spike,
        )

    def _check_vol_spike(self, current_atr: float, spread_bps: float) -> bool:
        """Check for volatility spike that should prevent aggressive execution"""
        if current_atr <= 0:
            return False

        # Simple volatility spike detection
        expected_spread = (
            current_atr * self._cfg["vol_spike_atr_mult"] * 1e4 / current_atr
        )
        return spread_bps > expected_spread

    def _calculate_expected_edges(
        self,
        side: str,
        quote: QuoteSnapshot,
        edge_bps: float,
        latency_ms: float,
        fill_features: Optional[Mapping[str, float]],
    ) -> Tuple[float, float]:
        """Calculate expected edges for maker and taker routes"""
        half_spread = quote.half_spread_bps
        E = float(edge_bps)

        # Taker edge (pay spread + taker fee)
        e_taker_pre = E - half_spread - self._fees.taker_fee_bps
        sla_res = self._sla.gate(edge_bps=e_taker_pre, latency_ms=latency_ms)
        e_taker = sla_res.edge_after_bps

        # Maker edge (earn spread if filled, minus maker fee)
        p_fill = self._estimate_p_fill(fill_features)
        e_maker = (E + half_spread - self._fees.maker_fee_bps) * p_fill

        return e_maker, e_taker

    def _determine_route(self, e_maker: float, e_taker: float, vol_spike: bool) -> str:
        """Determine optimal routing based on expected edges and constraints"""
        if vol_spike:
            return "deny"

        # Apply minimum edge thresholds
        min_edge_threshold = 0.1  # 0.1 bps minimum

        # Additional check: if taker is very negative AND initial edge was negative, deny
        # (This prevents trading in very bad market conditions with negative expectations)
        if e_taker <= -100.0:  # Only for extremely negative taker edges
            return "deny"

        if e_taker > min_edge_threshold and e_taker >= e_maker:
            return "taker"
        elif e_maker > min_edge_threshold:
            return "maker"
        else:
            return "deny"

    def _create_child_orders(
        self,
        symbol: str,
        side: str,
        target_qty: float,
        route: str,
        quote: QuoteSnapshot,
    ) -> List[ChildOrder]:
        """Create child orders for order splitting"""
        if target_qty <= self._cfg["min_lot"]:
            # Single order
            price = self._calculate_order_price(side, route, quote)
            return [
                ChildOrder(
                    qty=target_qty,
                    price=price,
                    order_type=route,
                    ttl_ms=(
                        self._cfg["taker_escalation_ttl_ms"] if route == "maker" else 0
                    ),
                )
            ]

        # Split into children
        num_children = min(
            self._cfg["max_children"], max(1, int(target_qty / self._cfg["min_lot"]))
        )

        qty_per_child = target_qty / num_children
        children = []

        for i in range(num_children):
            price = self._calculate_order_price(side, route, quote)
            child = ChildOrder(
                qty=qty_per_child,
                price=price,
                order_type=route,
                ttl_ms=self._cfg["taker_escalation_ttl_ms"] if route == "maker" else 0,
            )
            children.append(child)

        return children

    def _calculate_order_price(
        self, side: str, route: str, quote: QuoteSnapshot
    ) -> float:
        """Calculate order price based on side, route, and quote"""
        if route == "maker":
            offset_bps = self._cfg["maker_offset_bps"]
            if side.lower() == "buy":
                return quote.ask_px * (1.0 - offset_bps / 1e4)
            else:  # sell
                return quote.bid_px * (1.0 + offset_bps / 1e4)
        else:  # taker
            if side.lower() == "buy":
                return quote.ask_px
            else:  # sell
                return quote.bid_px

    def _calculate_repeg_trigger(self, quote: QuoteSnapshot) -> float:
        """Calculate spread threshold for re-peg trigger"""
        return min(quote.spread_bps * 0.5, self._cfg["spread_limit_bps"])

    def _estimate_p_fill(self, feats: Optional[Mapping[str, float]]) -> float:
        """Estimate probability of fill"""
        if self._haz is None or feats is None:
            return self._min_p

        try:
            horizon_ms = 1000.0  # 1 second default
            return self._haz.p_fill(horizon_ms, feats)
        except Exception:
            return self._min_p

    def should_repeg(
        self,
        symbol: str,
        current_spread_bps: float,
        trigger_bps: float,
        last_requote_ts: int,
    ) -> bool:
        """Check if order should be re-pegged based on spread movement"""
        now = int(time.time() * 1000)

        # Check minimum time between requotes
        if now - last_requote_ts < self._cfg["t_min_requote_ms"]:
            return False

        # Check requote rate limit
        minute_key = f"{symbol}_{now // 60000}"
        current_count = self._requote_counts.get(minute_key, 0)
        if current_count >= self._cfg["max_requotes_per_min"]:
            return False

        # Check spread trigger
        return current_spread_bps >= trigger_bps

    def record_requote(self, symbol: str) -> None:
        """Record a requote event for rate limiting"""
        now = int(time.time() * 1000)
        minute_key = f"{symbol}_{now // 60000}"
        self._requote_counts[minute_key] = self._requote_counts.get(minute_key, 0) + 1


__all__ = ["QuoteSnapshot", "ChildOrder", "ExecutionDecision", "EnhancedRouter"]
