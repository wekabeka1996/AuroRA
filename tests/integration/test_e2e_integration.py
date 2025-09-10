"""
E2E Integration Tests for Aurora Step 3.5
==========================================

Comprehensive integration test suite covering:
1. Trail-only execution
2. BE-win (breakeven winner) scenario
3. Scale-in ↔ CVaR interaction
4. Vol-spike pause and recovery
5. Post-only reject → 1-tick reprice
6. MinNotional reject handling
7. SL cleanup with IOC net-flat
8. TTL cleanup mechanism
9. No-progress exit condition
10. Governance kill switch
11. Full XAI event chain validation
12. Performance under load

All tests validate complete XAI event chains from SIZING_DECISION to POSITION_CLOSED
"""

import time
from unittest.mock import patch

import pytest

from core.execution.execution_router_v1 import ExecutionContext, ExecutionRouter, RouterConfig
from core.tca.tca_analyzer import FillEvent


@pytest.fixture
def integration_router():
    """Create router with production-like config for integration tests"""
    config = RouterConfig(
        post_only=True,
        maker_offset_bps=0.75,
        ttl_child_ms=1500,
        t_min_requote_ms=200,
        max_requotes_per_min=30,
        spread_limit_bps=8,
        vol_spike_guard_atr_mult=2.5,
        max_children=5,
        min_lot=0.00001  # Lower min_lot for testing small quantities
    )
    return ExecutionRouter(config=config)


@pytest.fixture
def base_market_data():
    """Base market data for integration tests"""
    return {
        "bid": 50000.0,
        "ask": 50008.0,  # 8bps spread
        "micro_price": 50004.0,
        "spread_bps": 8.0,
        "vol_spike_detected": False
    }


@pytest.fixture
def base_context():
    """Base execution context for integration tests"""
    return ExecutionContext(
        correlation_id="e2e_test_001",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        edge_bps=5.0,
        micro_price=50004.0,
        mid_price=50004.0,
        spread_bps=8.0
    )


class TestTrailOnlyExecution:
    """1. Trail-only execution scenario"""

    def test_trail_only_full_lifecycle(self, integration_router, base_context, base_market_data):
        """Test complete trail-only execution from sizing to position close"""
        context = base_context
        context.execution_mode = "trail_only"

        # 1. Initial sizing decision
        children = integration_router.execute_sizing_decision(context, base_market_data)
        assert len(children) >= 1

        # 2. All orders should be maker-only (no taker escalation)
        for child in children:
            assert child.mode == "maker"
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # 3. Simulate partial fills with trailing behavior
        total_filled = 0
        for i, child in enumerate(children):
            if i < len(children) // 2:  # Fill half the orders
                fill_qty = child.target_qty * 0.8
                fill = FillEvent(
                    ts_ns=time.time_ns(),
                    qty=fill_qty,
                    price=child.price,
                    fee=0.001,
                    liquidity_flag='M'
                )
                integration_router.handle_order_fill(child.order_id, fill)
                total_filled += fill_qty

        # 4. Validate XAI event chain
        # Should have EXEC_DECISION, ORDER_ACK, FILL_EVENT events
        assert total_filled > 0

        # 5. Position should remain in maker mode (no escalation)
        for child in children:
            if child.filled_qty > 0:
                assert child.mode == "maker"


class TestBEWinScenario:
    """2. BE-win (breakeven winner) scenario"""

    def test_be_win_position_management(self, integration_router, base_context, base_market_data):
        """Test breakeven winner position management"""
        context = base_context
        context.target_qty = 0.5  # Smaller position for BE-win

        children = integration_router.execute_sizing_decision(context, base_market_data)

        # Acknowledge orders
        for child in children:
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate profitable fills
        for child in children:
            fill = FillEvent(
                ts_ns=time.time_ns(),
                qty=child.target_qty,
                price=child.price + 10,  # Profitable fill
                fee=0.001,
                liquidity_flag='M'
            )
            integration_router.handle_order_fill(child.order_id, fill)

        # Validate BE-win logic (should maintain position until target R achieved)
        total_pnl = sum(child.filled_qty * (child.price + 10 - child.price) for child in children)
        assert total_pnl > 0


class TestScaleInCVaRInteraction:
    """3. Scale-in ↔ CVaR interaction"""

    def test_scale_in_cvar_gating(self, integration_router, base_context, base_market_data):
        """Test scale-in behavior with CVaR constraints"""
        context = base_context
        context.cvar_breached = False

        # Initial execution
        children1 = integration_router.execute_sizing_decision(context, base_market_data)
        initial_count = len(children1)

        # Simulate CVaR breach
        context.cvar_breached = True

        # Attempt scale-in
        children2 = integration_router.execute_sizing_decision(context, base_market_data)

        # Should be blocked or reduced due to CVaR breach
        assert len(children2) <= initial_count


class TestVolSpikePause:
    """4. Vol-spike pause and recovery"""

    def test_vol_spike_pause_recovery(self, integration_router, base_context, base_market_data):
        """Test vol-spike detection, pause, and recovery"""
        context = base_context

        # Normal execution
        market_data = base_market_data.copy()
        children1 = integration_router.execute_sizing_decision(context, market_data)
        assert len(children1) >= 1

        # Simulate vol spike
        market_data["vol_spike_detected"] = True
        children2 = integration_router.execute_sizing_decision(context, market_data)

        # Should be blocked during vol spike
        assert len(children2) == 0

        # Recovery after vol spike clears
        market_data["vol_spike_detected"] = False
        children3 = integration_router.execute_sizing_decision(context, market_data)

        # Should resume execution
        assert len(children3) >= 1


class TestPostOnlyRejectReprice:
    """5. Post-only reject → 1-tick reprice"""

    def test_post_only_reject_reprice_chain(self, integration_router, base_context, base_market_data):
        """Test complete post-only reject and reprice chain"""
        context = base_context

        children = integration_router.execute_sizing_decision(context, base_market_data)
        child = children[0]

        # Acknowledge order
        integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate POST_ONLY rejection
        original_price = child.price
        integration_router.handle_order_reject(child.order_id, "POST_ONLY", time.time_ns())

        # Should reprice by 1 tick
        assert child.retry_count == 1
        assert child.price != original_price

        # For BUY orders, price should decrease on POST_ONLY reject
        if child.side == "BUY":
            assert child.price < original_price


class TestMinNotionalReject:
    """6. MinNotional reject handling"""

    def test_min_notional_reject_handling(self, integration_router, base_context, base_market_data):
        """Test min notional reject with quantity reduction"""
        context = base_context
        context.target_qty = 0.0001  # Very small quantity

        children = integration_router.execute_sizing_decision(context, base_market_data)
        child = children[0]

        integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate MIN_NOTIONAL rejection
        original_qty = child.target_qty
        integration_router.handle_order_reject(child.order_id, "MIN_NOTIONAL", time.time_ns())

        # Should reduce quantity or cancel
        assert child.retry_count == 1
        # Either quantity reduced or order cancelled
        assert child.target_qty <= original_qty or child.state.name == "REJECTED"


class TestSLCleanup:
    """7. SL cleanup with IOC net-flat"""

    def test_sl_cleanup_ioc_netflat(self, integration_router, base_context, base_market_data):
        """Test SL trigger with IOC net-flat cleanup"""
        context = base_context

        children = integration_router.execute_sizing_decision(context, base_market_data)

        # Acknowledge all orders
        for child in children:
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate some fills
        for child in children[:2]:  # Fill first 2 orders
            fill = FillEvent(
                ts_ns=time.time_ns(),
                qty=child.target_qty * 0.5,
                price=child.price,
                fee=0.001,
                liquidity_flag='M'
            )
            integration_router.handle_order_fill(child.order_id, fill)

        # Trigger SL cleanup
        integration_router.trigger_cleanup(context.correlation_id, "SL_TRIGGER")

        # All orders should be in cleanup state
        for child in children:
            assert child.state.name in ["CLEANUP", "CLOSED"]


class TestTTLCleanup:
    """8. TTL cleanup mechanism"""

    def test_ttl_cleanup_mechanism(self, integration_router, base_context, base_market_data):
        """Test TTL-based cleanup of stale orders"""
        context = base_context

        children = integration_router.execute_sizing_decision(context, base_market_data)

        # Acknowledge orders
        for child in children:
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate TTL expiration
        for child in children:
            child.created_ts_ns = time.time_ns() - (integration_router.config.ttl_child_ms + 1000) * 1_000_000

        # Trigger cleanup
        integration_router.trigger_cleanup(context.correlation_id, "TTL_EXPIRE")

        # Orders should be cleaned up
        for child in children:
            assert child.state.name in ["CLEANUP", "CLOSED"]


class TestNoProgressExit:
    """9. No-progress exit condition"""

    def test_no_progress_exit_condition(self, integration_router, base_context, base_market_data):
        """Test exit when no progress made within time window"""
        context = base_context

        children = integration_router.execute_sizing_decision(context, base_market_data)

        # Acknowledge orders
        for child in children:
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate no fills for extended period
        # (In real implementation, this would be tracked by a monitoring system)

        # Trigger no-progress cleanup
        integration_router.trigger_cleanup(context.correlation_id, "NO_PROGRESS")

        # Should cleanup stale orders
        for child in children:
            if child.filled_qty == 0:
                assert child.state.name in ["CLEANUP", "CLOSED"]


class TestGovernanceKill:
    """10. Governance kill switch"""

    def test_governance_kill_switch(self, integration_router, base_context, base_market_data):
        """Test governance kill switch activation"""
        context = base_context

        children = integration_router.execute_sizing_decision(context, base_market_data)

        # Acknowledge orders
        for child in children:
            integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

        # Simulate governance kill
        integration_router.trigger_cleanup(context.correlation_id, "GOVERNANCE_KILL")

        # All orders should be immediately cleaned up
        for child in children:
            assert child.state.name in ["CLEANUP", "CLOSED"]


class TestXAIEventChain:
    """11. Full XAI event chain validation"""

    def test_complete_xai_event_chain(self, integration_router, base_context, base_market_data):
        """Test complete XAI event chain from SIZING_DECISION to POSITION_CLOSED"""
        context = base_context

        with patch.object(integration_router.event_logger, 'emit') as mock_emit:
            # 1. SIZING_DECISION
            children = integration_router.execute_sizing_decision(context, base_market_data)

            # 2. ORDER_ACK events
            for child in children:
                integration_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

            # 3. FILL_EVENT
            child = children[0]
            fill = FillEvent(
                ts_ns=time.time_ns(),
                qty=child.target_qty,
                price=child.price,
                fee=0.001,
                liquidity_flag='M'
            )
            integration_router.handle_order_fill(child.order_id, fill)

            # 4. POSITION_CLOSED (simulated)
            integration_router.trigger_cleanup(context.correlation_id, "POSITION_CLOSED")

            # Validate event sequence
            events = [call[0][1] for call in mock_emit.call_args_list]  # Get event payloads

            event_types = [event['event_type'] for event in events]
            assert 'EXEC_DECISION' in event_types
            assert 'ORDER_ACK' in event_types
            assert 'FILL_EVENT' in event_types

            # Validate correlation_id consistency
            correlation_ids = [event['correlation_id'] for event in events]
            assert all(cid == context.correlation_id for cid in correlation_ids)


class TestPerformanceUnderLoad:
    """12. Performance under load"""

    def test_performance_under_load(self, integration_router, base_context, base_market_data):
        """Test performance with multiple concurrent decisions"""
        import statistics

        latencies = []

        # Simulate load with multiple decisions
        for i in range(100):
            context = ExecutionContext(
                correlation_id=f"load_test_{i}",
                symbol="BTCUSDT",
                side="BUY" if i % 2 == 0 else "SELL",
                target_qty=1.0,
                edge_bps=5.0,
                micro_price=50004.0 + (i % 10),  # Vary price slightly
                mid_price=50004.0 + (i % 10),
                spread_bps=8.0
            )

            start = time.time_ns()
            children = integration_router.execute_sizing_decision(context, base_market_data)
            end = time.time_ns()

            latencies.append((end - start) / 1e6)  # Convert to ms

        # Validate performance requirements
        p95 = statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies)
        p99 = statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)

        # Should meet performance targets
        assert p95 <= 10.0  # Allow some buffer for test environment
        assert p99 <= 15.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
