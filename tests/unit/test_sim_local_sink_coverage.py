"""
Additional tests for core/execution/sim_local_sink.py to achieve 100% coverage
"""
from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
import time

from core.execution.sim_local_sink import SimLocalSink


def make_market(bid=99.0, ask=101.0, bid_qty=10.0, ask_qty=10.0):
    return {
        'best_bid': bid,
        'best_ask': ask,
        'liquidity': {'bid': bid_qty, 'ask': ask_qty},
        'depth': {'at_price': {}, 'levels_sum': {}},
        'traded_since_last': {},
    }


class TestSimLocalSinkAmend:
    """Test amend functionality."""

    def setup_method(self):
        """Setup test fixtures."""
        self.cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [0.0, 0.0]}}}
        self.sink = SimLocalSink(self.cfg)

    def test_amend_existing_order(self):
        """Test amending an existing order."""
        # Submit order
        order = {'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order)
        assert oid in self.sink._orders

        # Amend order
        amended = self.sink.amend(oid, {'price': 101.0, 'qty': 2.0})
        assert amended is True

        # Check order was updated
        assert self.sink._orders[oid]['price'] == 101.0
        assert self.sink._orders[oid]['qty'] == 2.0

    def test_amend_nonexistent_order(self):
        """Test amending a nonexistent order."""
        amended = self.sink.amend('nonexistent', {'price': 101.0})
        assert amended is False

    def test_amend_partial_fields(self):
        """Test amending with partial fields."""
        # Submit order
        order = {'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order)

        # Amend only price
        amended = self.sink.amend(oid, {'price': 102.0})
        assert amended is True
        assert self.sink._orders[oid]['price'] == 102.0
        assert self.sink._orders[oid]['qty'] == 1.0  # unchanged


class TestSimLocalSinkSubmitEdgeCases:
    """Test edge cases in submit method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [0.0, 0.0]}}}
        self.sink = SimLocalSink(self.cfg)

    def test_submit_limit_buy_crossing_ack(self):
        """Test limit buy order that crosses but should be acked (not post-only)."""
        cfg = {'order_sink': {'sim_local': {'post_only': False, 'ioc': False, 'latency_ms_range': [1, 1]}}}
        sink = SimLocalSink(cfg)
        market = make_market(bid=99.0, ask=100.0)

        # Submit limit buy at ask price (crossing)
        order = {'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = sink.submit(order, market)

        # Should be acked, not rejected
        assert oid in sink._orders
        # Check that order has required fields but no 'status' (that's in events)
        assert 'order_id' in sink._orders[oid]
        assert sink._orders[oid]['side'] == 'buy'
        assert sink._orders[oid]['price'] == 100.0

    def test_submit_limit_sell_crossing_ack(self):
        """Test limit sell order that crosses but should be acked."""
        cfg = {'order_sink': {'sim_local': {'post_only': False, 'ioc': False, 'latency_ms_range': [1, 1]}}}
        sink = SimLocalSink(cfg)
        market = make_market(bid=100.0, ask=101.0)

        # Submit limit sell at bid price (crossing)
        order = {'side': 'sell', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = sink.submit(order, market)

        # Should be acked, not rejected
        assert oid in sink._orders
        # Check that order has required fields
        assert 'order_id' in sink._orders[oid]
        assert sink._orders[oid]['side'] == 'sell'
        assert sink._orders[oid]['price'] == 100.0

    def test_submit_limit_no_crossing(self):
        """Test limit order that doesn't cross."""
        market = make_market(bid=99.0, ask=101.0)

        # Submit limit buy below ask
        order = {'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order, market)

        # Should be stored
        assert oid in self.sink._orders
        # Check that order has required fields
        assert 'order_id' in self.sink._orders[oid]
        assert self.sink._orders[oid]['side'] == 'buy'
        assert self.sink._orders[oid]['price'] == 100.0


class TestSimLocalSinkOnTickEdgeCases:
    """Test edge cases in on_tick method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [0.0, 0.0], 'ttl_ms': 1000}}}
        self.sink = SimLocalSink(self.cfg)

    def test_on_tick_partial_fill(self):
        """Test partial fill in on_tick."""
        # Submit limit order
        order = {'side': 'buy', 'qty': 10.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order)

        # Mock time function to control timing
        ts = [0]
        def tfunc():
            ts[0] += 100
            return ts[0]
        self.sink._time = tfunc

        # Simulate market snapshot with some traded volume
        market_snapshot = {
            'depth': {
                'at_price': {100.0: 5.0},  # 5 units ahead in queue
                'levels_sum': {100.0: 5.0}
            },
            'traded_since_last': {100.0: 3.0}  # 3 units traded
        }

        # Call on_tick
        self.sink.on_tick(market_snapshot)

        # Check partial fill occurred
        assert oid in self.sink._orders
        assert self.sink._orders[oid]['remaining'] < 10.0

    def test_on_tick_full_fill(self):
        """Test full fill in on_tick."""
        # Submit limit order
        order = {'side': 'buy', 'qty': 5.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order)

        # Mock time function
        ts = [0]
        def tfunc():
            ts[0] += 100
            return ts[0]
        self.sink._time = tfunc

        # Simulate market snapshot with enough traded volume for full fill
        market_snapshot = {
            'depth': {
                'at_price': {100.0: 0.0},  # No queue ahead
                'levels_sum': {100.0: 0.0}
            },
            'traded_since_last': {100.0: 10.0}  # More than enough traded
        }

        # Call on_tick
        self.sink.on_tick(market_snapshot)

        # Check order was fully filled and removed
        assert oid not in self.sink._orders

    def test_on_tick_ttl_expiry(self):
        """Test TTL expiry in on_tick."""
        # Mock time function to control timing
        ts = [0]
        def tfunc():
            ts[0] += 100
            return ts[0]
        
        cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [0.0, 0.0], 'ttl_ms': 500}}}
        sink = SimLocalSink(cfg, time_func=tfunc)
        
        # Submit limit order
        order = {'side': 'buy', 'qty': 5.0, 'order_type': 'limit', 'price': 100.0}
        oid = sink.submit(order)

        # Advance time past TTL
        ts[0] = 1000  # Past 500ms TTL

        # Call on_tick with no trading activity (fill_qty will be 0)
        market_snapshot = {
            'depth': {
                'at_price': {100.0: 10.0},  # Large queue ahead
                'levels_sum': {100.0: 10.0}
            },
            'traded_since_last': {100.0: 0.0}  # No trading
        }

        # Call on_tick
        sink.on_tick(market_snapshot)

        # Check order was cancelled due to TTL
        assert oid not in sink._orders

    def test_on_tick_market_order_ignored(self):
        """Test that market orders are ignored in on_tick."""
        # Submit market order
        order = {'side': 'buy', 'qty': 5.0, 'order_type': 'market'}
        oid = self.sink.submit(order, make_market())

        # Market orders should be filled immediately and removed
        assert oid not in self.sink._orders

        # Add a market order back manually to test on_tick ignores it
        self.sink._orders[oid] = {
            'side': 'buy',
            'qty': 5.0,
            'order_type': 'market',
            'remaining': 5.0,
            'created_ts_ms': 0
        }

        # Call on_tick
        market_snapshot = {
            'depth': {'at_price': {}, 'levels_sum': {}},
            'traded_since_last': {}
        }
        self.sink.on_tick(market_snapshot)

        # Market order should still be there (ignored by on_tick)
        assert oid in self.sink._orders


class TestSimLocalSinkCancelEdgeCases:
    """Test edge cases in cancel method."""

    def setup_method(self):
        """Setup test fixtures."""
        self.cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1]}}}
        self.sink = SimLocalSink(self.cfg)

    def test_cancel_nonexistent_order(self):
        """Test cancelling a nonexistent order."""
        result = self.sink.cancel('nonexistent')
        assert result is False

    def test_cancel_existing_order(self):
        """Test cancelling an existing order."""
        # Submit order
        order = {'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}
        oid = self.sink.submit(order)

        # Cancel order
        result = self.sink.cancel(oid)
        assert result is True
        assert oid not in self.sink._orders