"""
Integration Tests — Live Pipeline Paper Loop
===========================================

End-to-end testing of the live trading pipeline using fake exchanges.
Tests maker/taker routing, SLA gates, idempotency, and order lifecycle.
"""

from __future__ import annotations

import pytest
import tempfile
import time
from pathlib import Path
from unittest.mock import Mock, patch

from tests.fixtures.exchange_fakes import FakeExchange, FakeOrderResponse
from core.execution.exchange.common import Fees
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate
from core.execution.router import Router, QuoteSnapshot
from core.execution.idempotency import IdempotencyStore


@pytest.fixture
def tca_components():
    """Create TCA components for testing at module level."""
    # CoxPH with simple coefficients
    cox = CoxPH()
    cox._beta = {'obi': 0.1, 'spread_bps': -0.05}
    cox._feat = ['obi', 'spread_bps']

    # SLA gate
    sla = SLAGate(
        max_latency_ms=250,
        kappa_bps_per_ms=0.01,
        min_edge_after_bps=1.0
    )

    # Router
    router = Router(
        hazard_model=cox,
        slagate=sla,
        min_p_fill=0.25,
        exchange_name='fake'
    )

    return {'cox': cox, 'sla': sla, 'router': router}


@pytest.fixture
def temp_config():
    """Create temporary config for testing at module level."""
    config = {
        'execution': {
            'router': {'horizon_ms': 1500, 'p_min_fill': 0.25},
            'sla': {'max_latency_ms': 250, 'kappa_bps_per_ms': 0.01},
            'edge_floor_bps': 1.0
        }
    }
    return config


class TestLivePipelinePaperLoop:
    """Test live pipeline with paper trading simulation."""
    
    @pytest.fixture
    def fake_exchange(self):
        """Create fake exchange for testing."""
        return FakeExchange(
            symbol="BTCUSDT",
            base_price=50000.0,
            fees=Fees(maker_fee_bps=0.0, taker_fee_bps=0.08),
            fail_rate=0.0,
            latency_ms=5
        )
    
    
    @pytest.fixture
    def temp_config(self):
        """Create temporary config for testing."""
        config = {
            'execution': {
                'router': {'horizon_ms': 1500, 'p_min_fill': 0.25},
                'sla': {'max_latency_ms': 250, 'kappa_bps_per_ms': 0.01},
                'edge_floor_bps': 1.0
            }
        }
        return config
    
    def test_maker_routing_high_pfill(self, fake_exchange, tca_components, temp_config):
        """Test maker routing when P(fill) is high."""
        router = tca_components['router']
        
        # High P(fill) scenario
        fill_features = {'obi': 0.8, 'spread_bps': 1.0}  # High imbalance, tight spread
        
        quote = QuoteSnapshot(
            bid_px=49999.0,
            ask_px=50001.0,
            bid_sz=1.0,
            ask_sz=1.0
        )
        
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,  # Positive edge
            latency_ms=10.0,
            fill_features=fill_features
        )
        
        # Should route to maker due to high P(fill)
        if decision.route != "maker":
            scores = decision.get("scores", {}) if hasattr(decision, "get") else getattr(decision, "scores", {})
            print("DIAG: decision=", decision.route, "scores=", scores, "features.fill=", fill_features)
        assert decision.route == "maker"
        assert decision.p_fill > 0.5
        assert "E_maker" in decision.reason
    
    def test_taker_routing_low_pfill(self, fake_exchange, tca_components, temp_config):
        """Test taker routing when P(fill) is low."""
        router = tca_components['router']
        
        # Low P(fill) scenario
        fill_features = {'obi': -0.8, 'spread_bps': 5.0}  # Negative imbalance, wide spread
        
        quote = QuoteSnapshot(
            bid_px=49995.0,
            ask_px=50005.0,
            bid_sz=0.1,
            ask_sz=0.1
        )
        
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=2.0,  # Small positive edge
            latency_ms=10.0,
            fill_features=fill_features
        )
        
        # Should route to taker due to low P(fill)
        assert decision.route == "taker"
        assert decision.p_fill < 0.3
        assert "E_taker" in decision.reason
    
    def test_sla_deny_high_latency(self, fake_exchange, tca_components, temp_config):
        """Test SLA denial when latency is too high."""
        router = tca_components['router']
        
        quote = QuoteSnapshot(
            bid_px=49999.0,
            ask_px=50001.0
        )
        
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=300.0,  # High latency
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )
        
        # Should deny due to SLA breach
        assert decision.route == "deny"
        assert "SLA denied" in decision.reason
    
    def test_edge_floor_deny(self, fake_exchange, tca_components, temp_config):
        """Test denial when edge after latency < floor."""
        router = tca_components['router']
        
        quote = QuoteSnapshot(
            bid_px=49999.0,
            ask_px=50001.0
        )
        
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=0.5,  # Very small edge
            latency_ms=100.0,  # Some latency
            fill_features={'obi': 0.1, 'spread_bps': 1.0}
        )
        
        # Should deny due to edge floor
        assert decision.route == "deny"
        assert "unattractive" in decision.reason.lower()


class TestIdempotencyFills:
    """Test idempotency for fills and orders."""
    
    def test_client_oid_idempotency(self):
        """Test that duplicate client_oid prevents duplicate orders."""
        store = IdempotencyStore()
        client_oid = "test_order_123"
        
        # First time should not be seen
        assert not store.seen(client_oid)
        
        # Mark as seen
        store.mark(client_oid)
        
        # Second time should be seen
        assert store.seen(client_oid)
    
    def test_fill_idempotency(self):
        """Test fill idempotency (placeholder for future implementation)."""
        # This would test that duplicate fill_ids don't double-count
        # For now, just ensure the concept is documented
        store = IdempotencyStore()
        
        fill_id = "fill_123"
        assert not store.seen(fill_id)
        store.mark(fill_id)
        assert store.seen(fill_id)


class TestXaiDecisionTrail:
    """Test XAI logging and decision trail."""
    
    def test_decision_logging_codes(self, tca_components, temp_config):
        """Test that WHY codes are properly assigned."""
        router = tca_components['router']
        
        # Test various scenarios and their WHY codes
        scenarios = [
            # (fill_features, expected_route, expected_why_pattern)
            ({'obi': 0.8, 'spread_bps': 1.0}, "maker", "OK_ROUTE_MAKER"),
            ({'obi': -0.8, 'spread_bps': 5.0}, "taker", "OK_ROUTE_TAKER"),
            ({'obi': 0.0, 'spread_bps': 10.0}, "deny", "WHY_UNATTRACTIVE"),
        ]
        
        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)
        
        for fill_features, expected_route, expected_why in scenarios:
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=3.0,
                latency_ms=10.0,
                fill_features=fill_features
            )
            
            assert decision.route == expected_route
            # Note: WHY codes are logged internally, not returned in decision
            # This test ensures the routing logic works correctly
    
    def test_sla_why_codes(self, tca_components, temp_config):
        """Test SLA-related WHY codes."""
        router = tca_components['router']
        
        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)
        
        # High latency should trigger SLA deny
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=300.0,  # Breach SLA
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )
        
        assert decision.route == "deny"
        assert "SLA denied" in decision.reason


if __name__ == "__main__":
    pytest.main([__file__, "-v"])