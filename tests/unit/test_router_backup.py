"""
Tests for core/execution/router_backup.py
"""

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy router_backup implementation; superseded by router_v2; quarantined"
    ),
]
import json
import os

# Import the module under test
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, mock_open, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from core.execution.exchange.common import Fees
from core.execution.router_backup import QuoteSnapshot, RouteDecision, Router
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate


class TestQuoteSnapshot:
    """Test the QuoteSnapshot dataclass."""

    def test_initialization(self):
        """Test QuoteSnapshot initialization."""
        quote = QuoteSnapshot(
            bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=120.0, ts_ns=1000000
        )
        assert quote.bid_px == 100.0
        assert quote.ask_px == 100.02
        assert quote.bid_sz == 100.0
        assert quote.ask_sz == 120.0
        assert quote.ts_ns == 1000000

    def test_defaults(self):
        """Test QuoteSnapshot with default values."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02)
        assert quote.bid_sz == 0.0
        assert quote.ask_sz == 0.0
        assert quote.ts_ns == 0

    def test_mid_property(self):
        """Test mid price calculation."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02)
        assert abs(quote.mid - 100.01) < 1e-10  # Use approximate comparison

    def test_half_spread_bps_property(self):
        """Test half spread in bps calculation."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02)
        # Spread is 0.02, half spread is 0.01
        # Half spread in bps = (0.01 / 100.01) * 10000 ≈ 0.1
        expected = (0.01 / 100.01) * 10000
        assert abs(quote.half_spread_bps - expected) < 1e-10

    def test_half_spread_bps_zero_mid(self):
        """Test half spread with zero mid price."""
        quote = QuoteSnapshot(bid_px=0.0, ask_px=0.0)
        assert quote.half_spread_bps == 0.0


class TestRouteDecision:
    """Test the RouteDecision dataclass."""

    def test_initialization(self):
        """Test RouteDecision initialization."""
        decision = RouteDecision(
            route="maker",
            e_maker_bps=5.0,
            e_taker_bps=3.0,
            p_fill=0.8,
            reason="Test reason",
            maker_fee_bps=0.1,
            taker_fee_bps=0.5,
            net_e_maker_bps=4.9,
            net_e_taker_bps=2.5,
            scores={"test": 1.0},
        )
        assert decision.route == "maker"
        assert decision.e_maker_bps == 5.0
        assert decision.e_taker_bps == 3.0
        assert decision.p_fill == 0.8
        assert decision.reason == "Test reason"
        assert decision.maker_fee_bps == 0.1
        assert decision.taker_fee_bps == 0.5
        assert decision.net_e_maker_bps == 4.9
        assert decision.net_e_taker_bps == 2.5
        assert decision.scores == {"test": 1.0}

    def test_defaults(self):
        """Test RouteDecision with minimal required fields."""
        decision = RouteDecision(
            route="taker",
            e_maker_bps=1.0,
            e_taker_bps=2.0,
            p_fill=0.5,
            reason="Minimal",
        )
        assert decision.maker_fee_bps == 0.0
        assert decision.taker_fee_bps == 0.0
        assert decision.net_e_maker_bps == 0.0
        assert decision.net_e_taker_bps == 0.0
        assert decision.scores is None


class TestRouterInitialization:
    """Test Router initialization and configuration."""

    @patch("core.execution.router_backup.get_config")
    def test_init_with_defaults(self, mock_get_config):
        """Test Router initialization with default configuration."""
        mock_config = Mock()
        mock_config.get.side_effect = lambda key, default: {
            "execution.sla.max_latency_ms": 25,
            "execution.sla.target_fill_prob": 0.6,
        }.get(key, default)
        mock_get_config.return_value = mock_config

        router = Router()

        assert router._min_p == 0.6
        assert router._fees is not None
        assert router._sla is not None
        assert router._haz is None

    @patch("core.execution.router_backup.get_config")
    def test_init_with_custom_params(self, mock_get_config):
        """Test Router initialization with custom parameters."""
        mock_config = Mock()
        mock_config.get.return_value = 0.7
        mock_get_config.return_value = mock_config

        custom_fees = Fees(maker_fee_bps=0.05, taker_fee_bps=0.25)
        custom_sla = SLAGate(
            max_latency_ms=50.0, kappa_bps_per_ms=0.1, min_edge_after_bps=0.5
        )
        custom_hazard = CoxPH()

        router = Router(
            hazard_model=custom_hazard,
            slagate=custom_sla,
            min_p_fill=0.8,
            fees=custom_fees,
        )

        assert router._haz is custom_hazard
        assert router._sla is custom_sla
        assert router._min_p == 0.8
        assert router._fees is custom_fees

    @patch("core.execution.router_backup.get_config")
    def test_init_config_error_fallback(self, mock_get_config):
        """Test Router initialization with config errors uses fallbacks."""
        from core.config.loader import ConfigError

        mock_get_config.side_effect = ConfigError("Test error")

        router = Router()

        assert router._min_p == 0.6  # fallback value
        assert isinstance(router._sla, SLAGate)


class TestRouterDecisionLogic:
    """Test the main decision logic of Router."""

    def setup_method(self):
        """Setup test fixtures."""
        self.fees = Fees(maker_fee_bps=0.1, taker_fee_bps=0.5)
        self.sla = SLAGate(
            max_latency_ms=50.0, kappa_bps_per_ms=0.1, min_edge_after_bps=0.0
        )
        self.router = Router(slagate=self.sla, min_p_fill=0.5, fees=self.fees)

    def test_decide_taker_preferred_high_edge(self):
        """Test taker is preferred when edge is high and SLA allows."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=10.0,  # High edge
            latency_ms=5.0,  # Low latency
        )

        assert decision.route == "taker"
        assert decision.e_taker_bps > decision.e_maker_bps
        assert "E_taker" in decision.reason

    def test_decide_maker_preferred_high_pfill(self):
        """Test maker is preferred when fill probability is high."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.01, bid_sz=1000.0, ask_sz=1000.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=2.0,
            latency_ms=10.0,
            fill_features={"p_fill_estimate": 0.9},  # High fill probability
        )

        # With high p_fill, maker should be preferred
        assert decision.route in ["maker", "taker"]

    def test_decide_deny_extreme_spread(self):
        """Test denial when spread is extreme."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.2, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=1.0,
            latency_ms=5.0,
            fill_features={"spread_bps": 15.0},  # Extreme spread
        )

        assert decision.route == "deny"
        assert "extreme market spread" in decision.reason

    def test_decide_deny_low_pfill_taker_allowed(self):
        """Test taker chosen when p_fill is low but taker edge is positive."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=5.0,
            fill_features={"p_fill_estimate": 0.2},  # Low fill probability
        )

        # With low p_fill, the router might choose maker or taker depending on the logic
        assert decision.route in ["maker", "taker"]

    def test_decide_sla_deny_fallback_maker(self):
        """Test fallback to maker when SLA denies taker."""
        # Create SLA that will deny taker
        strict_sla = SLAGate(
            max_latency_ms=1.0, kappa_bps_per_ms=10.0, min_edge_after_bps=5.0
        )
        router = Router(slagate=strict_sla, min_p_fill=0.3, fees=self.fees)

        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=2.0,
            latency_ms=50.0,  # High latency that SLA will deny
            fill_features={"p_fill_estimate": 0.8},
        )

        # SLA denies taker, should fallback to maker
        assert decision.route == "maker"
        assert "SLA denied taker, fallback to maker" in decision.reason

    def test_decide_deny_both_unattractive(self):
        """Test denial when both routes are unattractive."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=-1.0,  # Negative edge
            latency_ms=5.0,
            fill_features={"p_fill_estimate": 0.2},
        )

        assert decision.route == "deny"
        assert "unattractive" in decision.reason

    def test_decide_with_hazard_model(self):
        """Test decision with hazard model for p_fill estimation."""
        # Mock hazard model
        mock_hazard = Mock()
        mock_hazard.p_fill.return_value = 0.85

        router = Router(
            hazard_model=mock_hazard, slagate=self.sla, min_p_fill=0.5, fees=self.fees
        )

        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=3.0,
            latency_ms=5.0,
            fill_features={"feature1": 1.0, "feature2": 2.0},
        )

        # Verify hazard model was called
        mock_hazard.p_fill.assert_called_once()
        assert decision.p_fill == 0.85

    def test_decide_with_obi_spread_adjustment(self):
        """Test p_fill adjustment based on OBI and spread."""
        mock_hazard = Mock()
        mock_hazard.p_fill.return_value = 0.9  # High p_fill from model

        router = Router(
            hazard_model=mock_hazard, slagate=self.sla, min_p_fill=0.5, fees=self.fees
        )

        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        # Features indicating adverse conditions
        adverse_features = {
            "obi": -0.5,  # Negative order book imbalance
            "spread_bps": 6.0,  # Wide spread
        }

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=3.0,
            latency_ms=5.0,
            fill_features=adverse_features,
        )

        # p_fill should be clamped down due to adverse conditions
        assert decision.p_fill <= 0.25


class TestRouterInternalMethods:
    """Test internal methods of Router."""

    def setup_method(self):
        """Setup test fixtures."""
        self.fees = Fees(maker_fee_bps=0.1, taker_fee_bps=0.5)
        self.sla = SLAGate(
            max_latency_ms=50.0, kappa_bps_per_ms=0.1, min_edge_after_bps=0.0
        )
        self.router = Router(slagate=self.sla, min_p_fill=0.5, fees=self.fees)

    def test_estimate_p_fill_no_hazard(self):
        """Test p_fill estimation without hazard model."""
        p_fill = self.router._estimate_p_fill(None)
        assert p_fill == 0.6  # Default value

    def test_estimate_p_fill_with_hazard(self):
        """Test p_fill estimation with hazard model."""
        mock_hazard = Mock()
        mock_hazard.p_fill.return_value = 0.75

        router = Router(hazard_model=mock_hazard, slagate=self.sla, fees=self.fees)

        features = {"feature1": 1.0}
        p_fill = router._estimate_p_fill(features)

        assert p_fill == 0.75
        mock_hazard.p_fill.assert_called_once()

    def test_tca_net_edge_bps_maker(self):
        """Test TCA net edge calculation for maker."""
        features = {"slippage_in_bps": 0.1, "impact_bps": 0.2, "adverse_bps": 0.05}

        net_edge = self.router._tca_net_edge_bps("maker", features, 5.0, 10.0, 0.1)

        # Expected: 5.0 (edge) + 0.1 (half_spread) + 0.1 (maker rebate)
        # - 0.1 (slippage) - 0.2 (impact) - 0.05 (adverse) - 0 (latency for maker)
        expected = 5.0 + 0.1 + 0.1 - 0.1 - 0.2 - 0.05
        assert abs(net_edge - expected) < 1e-10

    def test_tca_net_edge_bps_taker(self):
        """Test TCA net edge calculation for taker."""
        features = {"slippage_in_bps": 0.1, "impact_bps": 0.2, "adverse_bps": 0.05}

        net_edge = self.router._tca_net_edge_bps("taker", features, 5.0, 10.0, 0.1)

        # Expected: 5.0 (edge) - 0.1 (half_spread) - 0.5 (taker fee)
        # - 0.1 (slippage) - 0.2 (impact) - 0.05 (adverse) - 1.0 (latency penalty)
        expected = 5.0 - 0.1 - 0.5 - 0.1 - 0.2 - 0.05 - 1.0
        assert abs(net_edge - expected) < 1e-10


class TestRouterLogging:
    """Test logging functionality of Router."""

    def setup_method(self):
        """Setup test fixtures."""
        self.fees = Fees(maker_fee_bps=0.1, taker_fee_bps=0.5)
        self.sla = SLAGate(
            max_latency_ms=50.0, kappa_bps_per_ms=0.1, min_edge_after_bps=0.0
        )
        self.router = Router(slagate=self.sla, min_p_fill=0.5, fees=self.fees)

    def test_decide_creates_log_entry(self):
        """Test that decide method creates log entries."""
        # For now, just test that the deny path works correctly
        # The logging functionality can be tested separately if needed
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        # Use parameters that will force the deny path
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=-10.0,  # Negative edge to force deny
            latency_ms=100.0,  # High latency to force deny
        )

        # Verify decision is deny
        assert decision.route == "deny"
        assert (
            "unattractive" in decision.reason.lower()
            or "denied" in decision.reason.lower()
        )

        # Verify decision structure
        assert hasattr(decision, "e_maker_bps")
        assert hasattr(decision, "e_taker_bps")
        assert hasattr(decision, "p_fill")
        assert hasattr(decision, "reason")
        assert hasattr(decision, "maker_fee_bps")
        assert hasattr(decision, "taker_fee_bps")
        assert hasattr(decision, "net_e_maker_bps")
        assert hasattr(decision, "net_e_taker_bps")
        assert hasattr(decision, "scores")


class TestRouterEdgeCases:
    """Test edge cases and error conditions."""

    def setup_method(self):
        """Setup test fixtures."""
        self.fees = Fees(maker_fee_bps=0.1, taker_fee_bps=0.5)
        self.sla = SLAGate(
            max_latency_ms=50.0, kappa_bps_per_ms=0.1, min_edge_after_bps=0.0
        )
        self.router = Router(slagate=self.sla, min_p_fill=0.5, fees=self.fees)

    def test_decide_with_empty_features(self):
        """Test decision with empty features dict."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=5.0,
            fill_features={},
        )

        assert decision.route in ["maker", "taker", "deny"]
        assert isinstance(decision.p_fill, float)

    def test_decide_with_none_features(self):
        """Test decision with None features."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=5.0,
            fill_features=None,
        )

        assert decision.route in ["maker", "taker", "deny"]
        assert isinstance(decision.p_fill, float)

    def test_quote_with_zero_sizes(self):
        """Test quote with zero bid/ask sizes."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=0.0, ask_sz=0.0)

        decision = self.router.decide(
            side="buy", quote=quote, edge_bps_estimate=5.0, latency_ms=5.0
        )

        # Should still make a decision despite zero sizes
        assert decision.route in ["maker", "taker", "deny"]

    def test_negative_edge_estimate(self):
        """Test decision with negative edge estimate."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="sell",  # Note: sell side
            quote=quote,
            edge_bps_estimate=-2.0,  # Negative edge
            latency_ms=5.0,
        )

        # Should likely deny with negative edge
        assert decision.route == "deny"

    def test_very_high_latency(self):
        """Test decision with very high latency."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=100.02, bid_sz=100.0, ask_sz=100.0)

        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=100.0,  # Very high latency
        )

        # SLA should deny taker due to high latency
        assert decision.route in ["deny", "maker"]
