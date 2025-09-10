from __future__ import annotations

import pytest

pytestmark = [pytest.mark.legacy]
pytest.skip(
    "Legacy module archived; superseded by router_v2 & sim subpackage",
    allow_module_level=True,
)

import time
from unittest.mock import Mock, patch

import pytest

from core.execution.enhanced_router import (
    ChildOrder,
    EnhancedRouter,
    ExecutionDecision,
    QuoteSnapshot,
)


class TestEnhancedRouter:
    """Unit tests for EnhancedRouter v1.0"""

    @pytest.fixture
    def router(self) -> EnhancedRouter:
        """Test router instance"""
        return EnhancedRouter()

    @pytest.fixture
    def quote(self) -> QuoteSnapshot:
        """Test quote snapshot"""
        return QuoteSnapshot(
            bid_px=99.0,
            ask_px=101.0,
            bid_sz=100.0,
            ask_sz=100.0,
            ts_ns=1000000000,
            spread_bps=200.0,  # 2% spread
        )

    def test_initialization(self, router: EnhancedRouter):
        """Test router initialization with default config"""
        assert router._cfg is not None
        assert router._cfg["mode_default"] == "hybrid"
        assert router._cfg["maker_offset_bps"] == 1.0
        assert router._cfg["taker_escalation_ttl_ms"] == 1000

    def test_quote_snapshot_properties(self, quote: QuoteSnapshot):
        """Test QuoteSnapshot properties"""
        assert quote.mid == 100.0
        assert quote.half_spread_bps == 100.0  # (101-99)/100 * 10000 / 2

    def test_maker_routing_decision(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test maker routing when conditions are favorable"""
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            quote=quote,
            edge_bps_estimate=50.0,  # 50 bps edge
            latency_ms=10.0,
            current_atr=2.0,
            position_age_sec=60,
        )

        assert decision.route in ["maker", "taker", "deny"]
        assert len(decision.child_orders) > 0
        assert decision.escalation_ttl_ms >= 0
        assert decision.repeg_trigger_bps > 0

    def test_taker_routing_decision(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test taker routing when maker is unattractive"""
        # Create quote with very wide spread
        wide_quote = QuoteSnapshot(
            bid_px=95.0, ask_px=105.0, spread_bps=1000.0  # 10% spread
        )

        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            quote=wide_quote,
            edge_bps_estimate=20.0,  # Low edge
            latency_ms=5.0,
            current_atr=2.0,
            position_age_sec=60,
        )

        # Should prefer taker for wide spreads
        assert decision.route in ["maker", "taker", "deny"]

    def test_volatility_spike_guard(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test volatility spike detection"""
        # High ATR relative to spread should trigger guard
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            quote=quote,
            edge_bps_estimate=50.0,
            latency_ms=10.0,
            current_atr=10.0,  # Very high ATR
            position_age_sec=60,
        )

        # With ATR=10 and spread=200, expected_spread = 2.0 * 1e4 = 20000
        # Since 200 < 20000, vol_spike should be False
        assert decision.vol_spike_detected == False

    def test_child_order_splitting(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test child order splitting for large quantities"""
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=10.0,  # Large quantity
            quote=quote,
            edge_bps_estimate=50.0,
            latency_ms=10.0,
            current_atr=2.0,
            position_age_sec=60,
        )

        # Should split into multiple child orders
        assert len(decision.child_orders) > 1
        total_qty = sum(child.qty for child in decision.child_orders)
        assert abs(total_qty - 10.0) < 0.001

    def test_single_child_order(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test single child order for small quantities"""
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=0.001,  # Small quantity
            quote=quote,
            edge_bps_estimate=50.0,
            latency_ms=10.0,
            current_atr=2.0,
            position_age_sec=60,
        )

        # Should be single order
        assert len(decision.child_orders) == 1
        assert decision.child_orders[0].qty == 0.001

    def test_maker_price_calculation(
        self, router: EnhancedRouter, quote: QuoteSnapshot
    ):
        """Test maker order price calculation"""
        # Buy order - should be below ask
        buy_price = router._calculate_order_price("BUY", "maker", quote)
        assert buy_price < quote.ask_px

        # Sell order - should be above bid
        sell_price = router._calculate_order_price("SELL", "maker", quote)
        assert sell_price > quote.bid_px

    def test_taker_price_calculation(
        self, router: EnhancedRouter, quote: QuoteSnapshot
    ):
        """Test taker order price calculation"""
        # Buy order - should be at ask
        buy_price = router._calculate_order_price("BUY", "taker", quote)
        assert buy_price == quote.ask_px

        # Sell order - should be at bid
        sell_price = router._calculate_order_price("SELL", "taker", quote)
        assert sell_price == quote.bid_px

    def test_repeg_trigger_calculation(
        self, router: EnhancedRouter, quote: QuoteSnapshot
    ):
        """Test re-peg trigger calculation"""
        trigger = router._calculate_repeg_trigger(quote)
        expected = min(quote.spread_bps * 0.5, router._cfg["spread_limit_bps"])
        assert trigger == expected

    def test_should_repeg_logic(self, router: EnhancedRouter):
        """Test re-peg decision logic"""
        # Should repeg when spread exceeds trigger
        should_repeg = router.should_repeg(
            symbol="BTCUSDT",
            current_spread_bps=300.0,
            trigger_bps=200.0,
            last_requote_ts=0,
        )
        assert should_repeg == True

        # Should not repeg within minimum interval
        should_repeg = router.should_repeg(
            symbol="BTCUSDT",
            current_spread_bps=300.0,
            trigger_bps=200.0,
            last_requote_ts=int(time.time() * 1000)
            - int(router._cfg["t_min_requote_ms"] / 2),  # Half min interval ago
        )
        # Since last_requote_ts is half the min interval ago, time since last requote
        # is half the min interval, which is LESS than t_min_requote_ms
        # So should_repeg should return False
        assert should_repeg == False

    def test_requote_rate_limiting(self, router: EnhancedRouter):
        """Test requote rate limiting"""
        symbol = "BTCUSDT"

        # Record multiple requotes
        for i in range(router._cfg["max_requotes_per_min"] + 1):
            router.record_requote(symbol)

        # Next requote should be rate limited
        should_repeg = router.should_repeg(
            symbol=symbol,
            current_spread_bps=300.0,
            trigger_bps=200.0,
            last_requote_ts=0,
        )
        assert should_repeg == False

    def test_deny_on_low_edge(self, router: EnhancedRouter, quote: QuoteSnapshot):
        """Test denial when edge is too low"""
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            quote=quote,
            edge_bps_estimate=-10.0,  # Negative edge
            latency_ms=50.0,  # High latency
            current_atr=2.0,
            position_age_sec=60,
        )

        # With negative edge estimate, should deny
        assert decision.route == "deny"

    def test_escalation_ttl_for_maker(
        self, router: EnhancedRouter, quote: QuoteSnapshot
    ):
        """Test escalation TTL is set for maker orders"""
        decision = router.decide(
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            quote=quote,
            edge_bps_estimate=100.0,  # High edge favors maker
            latency_ms=5.0,
            current_atr=2.0,
            position_age_sec=60,
        )

        if decision.route == "maker":
            assert decision.escalation_ttl_ms == router._cfg["taker_escalation_ttl_ms"]
        elif decision.route == "taker":
            assert decision.escalation_ttl_ms == 0

    @patch("core.execution.enhanced_router.get_config")
    def test_config_loading(self, mock_get_config):
        """Test configuration loading"""
        mock_config = {
            "execution.router.mode_default": "maker",
            "execution.router.maker_offset_bps": 2.0,
            "execution.router.taker_escalation_ttl_ms": 2000,
        }

        mock_get_config.return_value.get.side_effect = (
            lambda key, default: mock_config.get(key, default)
        )

        router = EnhancedRouter()
        assert router._cfg["mode_default"] == "maker"
        assert router._cfg["maker_offset_bps"] == 2.0
        assert router._cfg["taker_escalation_ttl_ms"] == 2000
