"""
Unit Tests — Enhanced Idempotency & Partials Router v1.1
========================================================

Test enhanced idempotency handling and partial fill management
for ExecutionRouter v1.1 with IdempotencyStore and PartialSlicer integration.
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import Mock, patch
from dataclasses import dataclass

from core.execution.execution_router_v1 import ExecutionRouter, ExecutionContext
from core.tca.tca_analyzer import FillEvent


@dataclass 
class MockMarketData:
    """Mock market data for testing"""
    bid: float = 100.0
    ask: float = 100.1
    mid: float = 100.05
    spread_bps: float = 10.0


class TestEnhancedIdempotencyPartials:
    """Test enhanced idempotency and partial fill handling"""

    @pytest.fixture
    def router(self):
        """Create test router"""
        return ExecutionRouter()

    @pytest.fixture 
    def sample_context(self):
        """Sample execution context"""
        return ExecutionContext(
            symbol="ETHUSDT",
            side="BUY", 
            target_qty=1.0,
            correlation_id="test_123",
            edge_bps=5.0,
            micro_price=100.05,
            mid_price=100.0,
            spread_bps=10.0
        )

    @pytest.fixture
    def sample_market_data(self):
        """Sample market data"""
        return {
            "bid": 100.0,
            "ask": 100.1,
            "mid": 100.05,
            "spread_bps": 10.0,
            "vol_spike_detected": False
        }

    def test_enhanced_ack_idempotency(self, router, sample_context, sample_market_data):
        """Test enhanced ACK idempotency with IdempotencyStore"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        ack_ts = time.time_ns()
        
        # First ACK should work
        router.handle_order_ack(child.order_id, ack_ts, 5.0)
        assert child.state.value == "open"
        
        # Duplicate ACK with same timestamp should be ignored
        router.handle_order_ack(child.order_id, ack_ts, 5.0)
        assert child.state.value == "open"
        
        # Different timestamp ACK should also be ignored (order already open)
        router.handle_order_ack(child.order_id, ack_ts + 1000, 5.0)
        assert child.state.value == "open"

    def test_enhanced_fill_idempotency_by_trade_id(self, router, sample_context, sample_market_data):
        """Test fill idempotency using trade_id"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        # Create fill with trade_id
        fill = FillEvent(
            ts_ns=time.time_ns(),
            qty=0.1,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        fill.trade_id = "trade_123"  # Add trade_id
        
        # First fill
        router.handle_order_fill(child.order_id, fill)
        assert len(child.fills) == 1
        assert child.filled_qty == 0.1
        
        # Duplicate fill with same trade_id should be ignored
        router.handle_order_fill(child.order_id, fill)
        assert len(child.fills) == 1
        assert child.filled_qty == 0.1

    def test_enhanced_fill_idempotency_by_criteria(self, router, sample_context, sample_market_data):
        """Test fill idempotency by multiple criteria"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        ts = time.time_ns()
        fill = FillEvent(
            ts_ns=ts,
            qty=0.1,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        
        # First fill
        router.handle_order_fill(child.order_id, fill)
        assert len(child.fills) == 1
        
        # Duplicate with same ts, qty, price should be ignored
        fill_dup = FillEvent(
            ts_ns=ts,
            qty=0.1,
            price=child.price,
            fee=0.002,  # Different fee
            liquidity_flag='T'  # Different liquidity
        )
        router.handle_order_fill(child.order_id, fill_dup)
        assert len(child.fills) == 1  # Still 1

    def test_partial_slicer_integration(self, router, sample_context, sample_market_data):
        """Test PartialSlicer integration in router"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        # First partial fill - use smaller qty than child.target_qty
        fill_qty = child.target_qty * 0.3  # 30% of child order, not context
        fill1 = FillEvent(
            ts_ns=time.time_ns(),
            qty=fill_qty,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        router.handle_order_fill(child.order_id, fill1)
        
        # Should be PARTIAL state since filled_qty < target_qty
        assert child.state.value == "partial"
        
        # Check remaining quantity via router
        remaining = router.get_remaining_qty(child.order_id)
        expected_remaining = child.target_qty - fill_qty
        assert abs(remaining - expected_remaining) < 0.001  # Allow for floating point precision
        
        # Get next slice
        slice_info = router.get_next_slice(child.order_id, p_fill=0.8)
        assert slice_info is not None
        assert slice_info["qty"] > 0
        assert slice_info["remaining_after"] < remaining
        assert slice_info["idempotent"] is True

    def test_slice_idempotency_keys(self, router, sample_context, sample_market_data):
        """Test slice idempotency keys"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        # Partial fill - use smaller qty than child.target_qty  
        fill_qty = child.target_qty * 0.4  # 40% of child order
        fill = FillEvent(
            ts_ns=time.time_ns(),
            qty=fill_qty,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        router.handle_order_fill(child.order_id, fill)
        
        # Should be PARTIAL state
        assert child.state.value == "partial"
        
        # Get first slice
        slice1 = router.get_next_slice(child.order_id)
        assert slice1["idempotent"] is True
        
        # Mark slice as used in idempotency store
        router._idempotency_store.mark(slice1["slice_key"])
        
        # Get same slice again - should not be idempotent
        slice2 = router.get_next_slice(child.order_id)
        # Note: next_slice generates new slice with idx+1, so this should be different
        assert slice2["slice_idx"] == slice1["slice_idx"] + 1

    def test_late_fill_idempotency(self, router, sample_context, sample_market_data):
        """Test late fill idempotency (after order cleanup)"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        # Cancel order (cleanup)
        router.handle_order_cancel(child.order_id, time.time_ns())
        
        # Late fill arrives
        fill = FillEvent(
            ts_ns=time.time_ns(),
            qty=0.1,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        
        # Should not crash and should be logged
        router.handle_order_fill(child.order_id, fill)
        
        # Duplicate late fill should be ignored by idempotency
        router.handle_order_fill(child.order_id, fill)

    def test_idempotency_store_cleanup(self, router):
        """Test idempotency store cleanup"""
        # Add some entries
        router._idempotency_store.mark("test1", ttl_sec=0.1)
        router._idempotency_store.mark("test2", ttl_sec=300)
        
        initial_size = router._idempotency_store.size()
        assert initial_size >= 2
        
        # Wait for first to expire
        time.sleep(0.2)
        
        # Cleanup via router
        removed = router.cleanup_idempotency_store()
        assert removed >= 1
        
        final_size = router._idempotency_store.size()
        assert final_size < initial_size

    def test_partial_fill_state_transitions(self, router, sample_context, sample_market_data):
        """Test state transitions with partial fills and slicing"""
        context = sample_context
        children = router.execute_sizing_decision(context, sample_market_data)
        
        child = children[0]
        router.handle_order_ack(child.order_id, time.time_ns(), 5.0)
        
        # First partial fill - use smaller qty than child.target_qty
        fill_qty = child.target_qty * 0.3  # 30% of child order
        fill1 = FillEvent(
            ts_ns=time.time_ns(),
            qty=fill_qty,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        router.handle_order_fill(child.order_id, fill1)
        assert child.state.value == "partial"
        
        # Complete the order (remaining 70%)
        remaining_qty = child.target_qty - fill_qty
        fill2 = FillEvent(
            ts_ns=time.time_ns() + 1000,
            qty=remaining_qty,
            price=child.price,
            fee=0.001,
            liquidity_flag='M'
        )
        router.handle_order_fill(child.order_id, fill2)
        assert child.state.value == "closed"
        
        # Check partial slicer was cleaned up
        remaining = router.get_remaining_qty(child.order_id)
        assert remaining == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])