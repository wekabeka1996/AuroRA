"""
Tests for core/execution/router_new.py
"""
import pytest
from unittest.mock import Mock

# Import the module under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.execution.router_new import (
    Router, Decision, _clip01, _estimate_p_fill
)


class TestDecision:
    """Test Decision dataclass."""

    def test_decision_creation(self):
        """Test Decision dataclass creation."""
        decision = Decision(
            route="maker",
            why_code="OK_ROUTE_MAKER",
            scores={"p_fill": 0.8, "edge_bps": 5.0}
        )
        
        assert decision.route == "maker"
        assert decision.why_code == "OK_ROUTE_MAKER"
        assert decision.scores == {"p_fill": 0.8, "edge_bps": 5.0}

    def test_decision_with_deny_route(self):
        """Test Decision with deny route."""
        decision = Decision(
            route="deny",
            why_code="WHY_SLA_LATENCY",
            scores={"latency_ms": 300.0, "max_latency_ms": 250.0}
        )
        
        assert decision.route == "deny"
        assert decision.why_code == "WHY_SLA_LATENCY"
        assert decision.scores["latency_ms"] == 300.0


class TestClip01:
    """Test _clip01 utility function."""

    def test_clip01_negative(self):
        """Test _clip01 with negative value."""
        assert _clip01(-1.0) == 0.0
        assert _clip01(-0.5) == 0.0

    def test_clip01_zero(self):
        """Test _clip01 with zero."""
        assert _clip01(0.0) == 0.0

    def test_clip01_positive(self):
        """Test _clip01 with positive value."""
        assert _clip01(0.5) == 0.5
        assert _clip01(0.8) == 0.8

    def test_clip01_one(self):
        """Test _clip01 with one."""
        assert _clip01(1.0) == 1.0

    def test_clip01_above_one(self):
        """Test _clip01 with value above one."""
        assert _clip01(1.5) == 1.0
        assert _clip01(2.0) == 1.0


class TestEstimatePFill:
    """Test _estimate_p_fill function."""

    def test_estimate_p_fill_default(self):
        """Test _estimate_p_fill with default features."""
        features = {}
        p_fill = _estimate_p_fill(features)
        assert p_fill == 0.5  # 0.5 + 0.5 * 0.0 - 0.05 * 0.0

    def test_estimate_p_fill_with_obi(self):
        """Test _estimate_p_fill with OBI feature."""
        features = {"obi": 0.5}
        p_fill = _estimate_p_fill(features)
        assert p_fill == 0.75  # 0.5 + 0.5 * 0.5 - 0.05 * 0.0

    def test_estimate_p_fill_with_spread(self):
        """Test _estimate_p_fill with spread feature."""
        features = {"spread_bps": 5.0}
        p_fill = _estimate_p_fill(features)
        assert p_fill == 0.25  # 0.5 + 0.5 * 0.0 - 0.05 * 5.0

    def test_estimate_p_fill_with_both_features(self):
        """Test _estimate_p_fill with both OBI and spread."""
        features = {"obi": 0.6, "spread_bps": 4.0}
        p_fill = _estimate_p_fill(features)
        expected = 0.5 + 0.5 * 0.6 - 0.05 * 4.0
        assert abs(p_fill - expected) < 1e-10

    def test_estimate_p_fill_clipping(self):
        """Test _estimate_p_fill with extreme values that require clipping."""
        # High OBI, low spread -> should be clipped to 1.0
        features = {"obi": 1.0, "spread_bps": 0.0}
        p_fill = _estimate_p_fill(features)
        assert p_fill == 1.0

        # Low OBI, high spread -> should be clipped to 0.0
        features = {"obi": -1.0, "spread_bps": 20.0}
        p_fill = _estimate_p_fill(features)
        assert p_fill == 0.0


class TestRouter:
    """Test Router class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.config = {
            "execution": {
                "edge_floor_bps": 1.0,
                "router": {
                    "horizon_ms": 1500,
                    "p_min_fill": 0.25,
                    "spread_deny_bps": 8.0,
                    "maker_spread_ok_bps": 2.0,
                    "switch_margin_bps": 0.0
                },
                "sla": {
                    "kappa_bps_per_ms": 0.01,
                    "max_latency_ms": 250
                }
            }
        }
        self.router = Router(self.config)

    def test_router_init_with_config(self):
        """Test Router initialization with config."""
        assert self.router.edge_floor_bps == 1.0
        assert self.router.p_min_fill == 0.25
        assert self.router.horizon_ms == 1500
        assert self.router.kappa_bps_per_ms == 0.01
        assert self.router.max_latency_ms == 250
        assert self.router.spread_deny_bps == 8.0
        assert self.router.maker_spread_ok_bps == 2.0
        assert self.router.switch_margin_bps == 0.0

    def test_router_init_with_empty_config(self):
        """Test Router initialization with empty config."""
        router = Router({})
        assert router.edge_floor_bps == 0.0
        assert router.p_min_fill == 0.25
        assert router.horizon_ms == 1500
        assert router.kappa_bps_per_ms == 0.0
        assert router.max_latency_ms == float("inf")
        assert router.spread_deny_bps == 8.0
        assert router.maker_spread_ok_bps == 2.0
        assert router.switch_margin_bps == 0.0

    def test_router_init_with_partial_config(self):
        """Test Router initialization with partial config."""
        config = {
            "execution": {
                "edge_floor_bps": 2.0,
                "router": {
                    "p_min_fill": 0.3
                }
            }
        }
        router = Router(config)
        assert router.edge_floor_bps == 2.0
        assert router.p_min_fill == 0.3
        assert router.horizon_ms == 1500  # default
        assert router.kappa_bps_per_ms == 0.0  # default
        assert router.max_latency_ms == float("inf")  # default


class TestRouterDecide:
    """Test Router.decide method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.config = {
            "execution": {
                "edge_floor_bps": 1.0,
                "router": {
                    "horizon_ms": 1500,
                    "p_min_fill": 0.25,
                    "spread_deny_bps": 8.0,
                    "maker_spread_ok_bps": 2.0,
                    "switch_margin_bps": 0.0
                },
                "sla": {
                    "kappa_bps_per_ms": 0.01,
                    "max_latency_ms": 250
                }
            }
        }
        self.router = Router(self.config)

    def test_decide_sla_latency_deny(self):
        """Test decide with SLA latency deny."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=300.0,  # Above max_latency_ms
            fill_features={}
        )
        
        assert decision.route == "deny"
        assert decision.why_code == "WHY_SLA_LATENCY"
        assert decision.scores["latency_ms"] == 300.0
        assert decision.scores["max_latency_ms"] == 250

    def test_decide_spread_deny(self):
        """Test decide with spread deny."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=100.0,
            fill_features={"spread_bps": 10.0}  # Above spread_deny_bps
        )
        
        assert decision.route == "deny"
        assert decision.why_code == "WHY_UNATTRACTIVE"
        assert decision.scores["spread_bps"] == 10.0
        assert decision.scores["spread_deny_bps"] == 8.0

    def test_decide_edge_floor_deny(self):
        """Test decide with edge floor deny."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=0.5,  # Below edge_floor_bps after latency penalty
            latency_ms=100.0,
            fill_features={"spread_bps": 2.0}
        )
        
        assert decision.route == "deny"
        assert decision.why_code == "WHY_UNATTRACTIVE"
        assert "edge_after_latency_bps" in decision.scores
        assert "edge_floor_bps" in decision.scores

    def test_decide_maker_route(self):
        """Test decide with maker route."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=50.0,
            fill_features={
                "spread_bps": 1.0,  # Below maker_spread_ok_bps
                "obi": 0.8  # High OBI for high p_fill
            }
        )
        
        assert decision.route == "maker"
        assert decision.why_code == "OK_ROUTE_MAKER"
        assert "p_fill" in decision.scores
        assert "spread_bps" in decision.scores
        assert "edge_after_latency_bps" in decision.scores

    def test_decide_taker_route(self):
        """Test decide with taker route."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=50.0,
            fill_features={
                "spread_bps": 5.0,  # Above maker_spread_ok_bps
                "obi": 0.2  # Low OBI for low p_fill
            }
        )
        
        assert decision.route == "taker"
        assert decision.why_code == "OK_ROUTE_TAKER"
        assert "p_fill" in decision.scores
        assert "spread_bps" in decision.scores
        assert "edge_after_latency_bps" in decision.scores

    def test_decide_boundary_conditions(self):
        """Test decide with boundary conditions."""
        quote = Mock()
        
        # Test exactly at max latency (should allow)
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=250.0,  # Exactly at max
            fill_features={"spread_bps": 1.0, "obi": 0.8}
        )
        assert decision.route == "maker"  # Should not be denied
        
        # Test exactly at spread deny threshold (should deny)
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=50.0,
            fill_features={"spread_bps": 8.0, "obi": 0.8}  # Exactly at threshold
        )
        assert decision.route == "deny"  # Should be denied (>= threshold)

    def test_decide_with_minimal_features(self):
        """Test decide with minimal fill features."""
        quote = Mock()
        decision = self.router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=50.0,
            fill_features={}  # Empty features
        )
        
        # Should default to taker since p_fill = 0.5, spread_bps = 0.0
        # p_fill >= max(0.25, 0.5) = 0.5, so p_fill >= 0.5 is True
        # spread_bps <= 2.0 is True, so prefer_maker should be True
        assert decision.route == "maker"
        assert decision.why_code == "OK_ROUTE_MAKER"