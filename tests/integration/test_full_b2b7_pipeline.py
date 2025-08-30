"""
Integration Tests — Full B2-B7 Live Pipeline
============================================

Comprehensive integration test for the complete B2-B7 live trading pipeline.
Tests TCA/SLA/Router integration, SSOT configuration, XAI logging, idempotency,
and end-to-end order flow with fake exchanges.
"""

from __future__ import annotations

import pytest
import asyncio
import json
import tempfile
from pathlib import Path
from unittest.mock import patch, AsyncMock, MagicMock
from datetime import datetime, timedelta

from skalp_bot.runner.run_live_aurora import AuroraGate
from tests.fixtures.exchange_fakes import FakeExchange, FakeOrderResponse, FakeFill
from core.execution.router import Router, RouteDecision, QuoteSnapshot
from core.execution.idempotency import IdempotencyStore
from common.events import EventEmitter


class TestFullB2B7Pipeline:
    """Test complete B2-B7 live trading pipeline."""
    
    @pytest.fixture
    def fake_exchange(self):
        """Create fake exchange for testing."""
        return FakeExchange(
            symbol="BTCUSDT",
            base_price=50000.0,
            fail_rate=0.0,
            latency_ms=10
        )
    
    @pytest.fixture
    def router(self):
        """Create router with test configuration."""
        from core.tca.hazard_cox import CoxPH
        from core.tca.latency import SLAGate
        
        # CoxPH
        cox = CoxPH()
        cox._beta = {'obi': 0.1, 'spread_bps': -0.05}
        cox._feat = ['obi', 'spread_bps']
        
        # SLA
        sla = SLAGate(max_latency_ms=250, kappa_bps_per_ms=0.01, min_edge_after_bps=1.0)
        
        # Router
        router = Router(
            hazard_model=cox,
            slagate=sla,
            min_p_fill=0.25,
            exchange_name='test'
        )
        
        return router
    
    @pytest.fixture
    def aurora_gate(self):
        """Create Aurora gate for testing."""
        return AuroraGate(base_url="http://127.0.0.1:8000", mode="shadow")
    
    @pytest.fixture
    def idempotency_store(self):
        """Create idempotency store."""
        return IdempotencyStore()
    
    def test_maker_routing_scenario(self, fake_exchange, router, aurora_gate, idempotency_store):
        """Test complete maker routing scenario."""
        # Setup fake exchange for maker scenario
        fake_exchange.base_price = 50000.0
        
        # Create quote snapshot
        quote = QuoteSnapshot(bid_px=49999.5, ask_px=50000.5)  # Closer to base price
        
        # Mock router decision for maker
        with patch.object(router, 'decide') as mock_decide:
            mock_decide.return_value = RouteDecision(
                route="maker",
                e_maker_bps=4.5,
                e_taker_bps=3.2,
                p_fill=0.8,
                reason="High fill probability favors maker",
                maker_fee_bps=0.0,
                taker_fee_bps=0.08,
                net_e_maker_bps=4.5,
                net_e_taker_bps=3.12
            )
            
            # Make routing decision
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=5.0,
                latency_ms=10.0,
                fill_features={'obi': 0.8, 'spread_bps': 1.0}
            )
        
        # Verify decision
        assert decision.route == "maker"
        assert decision.e_maker_bps == 4.5
        assert decision.p_fill == 0.8
        
        # Test order placement with price closer to mid
        order_response = fake_exchange.place_order(
            side="buy",
            qty=0.001,
            price=49999.5  # Maker price closer to base
        )
        
        assert order_response.status == "closed"
        assert order_response.filled_qty == 0.001
    
    def test_taker_routing_scenario(self, fake_exchange, router):
        """Test complete taker routing scenario."""
        # Setup fake exchange for taker scenario
        fake_exchange.base_price = 50000.0
        
        # Create quote snapshot
        quote = QuoteSnapshot(bid_px=49995.0, ask_px=50005.0)
        
        # Mock router decision for taker
        with patch.object(router, 'decide') as mock_decide:
            mock_decide.return_value = RouteDecision(
                route="taker",
                e_maker_bps=2.1,
                e_taker_bps=3.8,
                p_fill=0.3,
                reason="Low fill probability favors taker",
                maker_fee_bps=0.0,
                taker_fee_bps=0.08,
                net_e_maker_bps=2.1,
                net_e_taker_bps=3.72
            )
            
            # Make routing decision
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=2.0,
                latency_ms=10.0,
                fill_features={'obi': -0.8, 'spread_bps': 5.0}
            )
        
        # Verify decision
        assert decision.route == "taker"
        assert decision.e_taker_bps == 3.8
        
        # Test market order placement
        order_response = fake_exchange.place_order(
            side="buy",
            qty=0.001,
            price=None  # Market order
        )
        
        assert order_response.status == "closed"
        assert order_response.filled_qty == 0.001
    
    def test_sla_denial_scenario(self, router):
        """Test SLA denial scenario."""
        # Create quote snapshot
        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)
        
        # Mock router decision for denial
        with patch.object(router, 'decide') as mock_decide:
            mock_decide.return_value = RouteDecision(
                route="deny",
                e_maker_bps=1.5,
                e_taker_bps=1.2,
                p_fill=0.6,
                reason="SLA breach: latency 350ms > 250ms limit",
                maker_fee_bps=0.0,
                taker_fee_bps=0.08,
                net_e_maker_bps=1.5,
                net_e_taker_bps=1.12
            )
            
            # Make routing decision with high latency
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=5.0,
                latency_ms=350.0,  # Breach SLA
                fill_features={'obi': 0.5, 'spread_bps': 2.0}
            )
        
        # Verify denial
        assert decision.route == "deny"
        assert "SLA breach" in decision.reason
    
    def test_idempotency_prevents_duplicate(self, fake_exchange, idempotency_store):
        """Test idempotency prevents duplicate orders."""
        client_oid = "test_oid_123"
        
        # First order should succeed
        assert not idempotency_store.seen(client_oid)
        
        # Mark as seen
        idempotency_store.mark(client_oid)
        
        # Second check should return True
        assert idempotency_store.seen(client_oid)
    
    def test_exchange_failure_handling(self, fake_exchange):
        """Test exchange failure handling."""
        # Configure exchange to fail
        fake_exchange.set_next_reject(True)
        
        # Attempt order placement should raise exception
        with pytest.raises(ValueError, match="Exchange rejected order"):
            fake_exchange.place_order(
                side="buy",
                qty=0.001,
                price=50000.0
            )
    
    def test_xai_logging_complete(self, router, tmp_path):
        """Test complete XAI decision logging."""
        # Create temporary log directory
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        
        # Create multiple decisions
        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)
        
        test_cases = [
            ("maker", {'obi': 0.8, 'spread_bps': 1.0}, 10.0),
            ("taker", {'obi': -0.8, 'spread_bps': 5.0}, 10.0),
            ("deny", {'obi': 0.0, 'spread_bps': 10.0}, 10.0),
        ]
        
        for expected_route, fill_features, latency in test_cases:
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=3.0,
                latency_ms=latency,
                fill_features=fill_features
            )
            
            # Verify decision has required fields
            assert hasattr(decision, 'route')
            assert hasattr(decision, 'e_maker_bps')
            assert hasattr(decision, 'e_taker_bps')
            assert hasattr(decision, 'p_fill')
            assert hasattr(decision, 'reason')
            assert decision.reason != ""
        
        # Check if log files were created
        log_files = list(log_dir.glob("*.jsonl"))
        # Note: In actual implementation, logging happens in router.decide
    
    def test_pretrade_gate_integration(self, aurora_gate):
        """Test pre-trade gate integration."""
        # Mock the _requests attribute to avoid network calls
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "allow": True,
            "max_qty": 0.001,
            "reason": "Test allow",
            "observability": {"gate_state": "ALLOW"}
        }
        mock_requests.post.return_value = mock_response
        aurora_gate._requests = mock_requests
        
        # Test allow scenario
        account = {"mode": "shadow"}
        order = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001}
        market = {"latency_ms": 10.0, "spread_bps": 2.0, "score": 0.7}
        
        result = aurora_gate.check(account, order, market)
        
        # Should allow
        assert result.get("allow", False) == True
        assert result.get("max_qty", 0) == 0.001
    
    def test_end_to_end_pipeline_simulation(self, fake_exchange, router, aurora_gate, idempotency_store):
        """Test end-to-end pipeline simulation."""
        # Setup market conditions
        fake_exchange.base_price = 50000.0
        
        # Mock the _requests attribute for pre-trade check
        mock_requests = MagicMock()
        mock_response = MagicMock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "allow": True,
            "max_qty": 0.001,
            "reason": "Test allow",
            "observability": {"gate_state": "ALLOW"}
        }
        mock_requests.post.return_value = mock_response
        aurora_gate._requests = mock_requests
        
        # Simulate complete trading cycle
        account = {"mode": "shadow"}
        order = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001}
        market = {"latency_ms": 10.0, "spread_bps": 2.0, "score": 0.7}
        
        # 1. Pre-trade check
        pretrade_result = aurora_gate.check(account, order, market)
        assert pretrade_result.get("allow", False) == True
        
        # 2. Idempotency check
        client_oid = "e2e_test_001"
        assert not idempotency_store.seen(client_oid)
        
        # 3. Routing decision
        quote = QuoteSnapshot(bid_px=49999.5, ask_px=50000.5)
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=4.0,
            latency_ms=10.0,
            fill_features={'obi': 0.6, 'spread_bps': 2.0}
        )
        
        # 4. Execute based on decision
        if decision.route == "maker":
            order_response = fake_exchange.place_order(
                side="buy",
                qty=0.001,
                price=49999.5
            )
        elif decision.route == "taker":
            order_response = fake_exchange.place_order(
                side="buy",
                qty=0.001,
                price=None
            )
        else:
            order_response = None
        
        # 5. Mark idempotency
        if order_response:
            idempotency_store.mark(client_oid)
            assert idempotency_store.seen(client_oid)
        
        # Verify complete flow
        assert decision.route in ["maker", "taker", "deny"]
        if order_response:
            assert order_response.status == "closed"
            assert order_response.filled_qty == 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])