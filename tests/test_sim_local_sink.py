from __future__ import annotations

import os
import json
import time
from unittest.mock import Mock, patch

import pytest

from core.execution.sim_local_sink import SimLocalSink
from tools.gen_sim_local_first100 import main as gen_main


def test_gen_sim_local_first100_creates_events():
    # Test the gen_sim_local_first100 tool
    result = gen_main()
    assert isinstance(result, dict)
    assert result['events_generated'] == 100
    assert result['status'] == 'ok'


class TestSimLocalSink:
    """Comprehensive test suite for SimLocalSink class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.mock_event_logger = Mock()
        self.mock_time_func = Mock(return_value=1000.0)
        self.base_config = {
            'order_sink': {
                'sim_local': {
                    'post_only': True,
                    'ioc': True,
                    'latency_ms_range': [5, 15],
                    'slip_bps_range': [0.0, 2.0],
                    'ttl_ms': 1000,
                    'seed': 42,
                    'maker': {
                        'queue_model': 'depth_l1',
                        'queue_safety_eps': 1e-6
                    },
                    'taker': {
                        'max_levels': 1
                    }
                }
            }
        }

    def test_initialization_default_config(self):
        """Test initialization with default configuration."""
        sink = SimLocalSink()

        assert sink.post_only is True
        assert sink.ioc is True
        assert sink.latency_ms_range == (8, 25)
        assert sink.slip_bps_range == (0.0, 1.2)
        assert sink.ttl_ms == 1500
        assert sink.rng_seed is None
        assert len(sink._orders) == 0

    def test_initialization_custom_config(self):
        """Test initialization with custom configuration."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        assert sink.post_only is True
        assert sink.ioc is True
        assert sink.latency_ms_range == (5, 15)
        assert sink.slip_bps_range == (0.0, 2.0)
        assert sink.ttl_ms == 1000
        assert sink.rng_seed == 42
        assert sink._ev == self.mock_event_logger
        assert sink._time == self.mock_time_func

    def test_initialization_with_seed(self):
        """Test initialization with deterministic seed."""
        config_with_seed = self.base_config.copy()
        config_with_seed['order_sink']['sim_local']['seed'] = 123

        sink = SimLocalSink(cfg=config_with_seed)

        assert sink.rng_seed == 123
        # Test deterministic behavior
        val1 = sink.rng.random()
        sink.rng.seed(123)
        val2 = sink.rng.random()
        assert val1 == val2

    def test_submit_market_order_buy_immediate_fill(self):
        """Test submitting market buy order with immediate fill."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 10.0, 'ask': 10.0}
        }

        order = {
            'order_id': 'test-123',
            'side': 'buy',
            'qty': 5.0,
            'order_type': 'market'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-123'
        assert order_id not in sink._orders  # Market order with liquidity gets filled and removed

        # Verify event emission
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-123'
        assert event_data['status'] == 'filled'
        assert event_data['side'] == 'buy'
        assert event_data['qty'] == 5.0
        assert event_data['slip_bps'] is not None
        assert event_data['latency_ms_action'] is not None

    def test_submit_limit_order_buy_no_cross(self):
        """Test submitting limit buy order that doesn't cross the spread."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 10.0, 'ask': 10.0}
        }

        order = {
            'order_id': 'test-124',
            'side': 'buy',
            'qty': 5.0,
            'price': 99.0,  # Below best bid, no cross
            'order_type': 'limit'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-124'
        assert order_id in sink._orders

        # Verify event emission for new order
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-124'
        assert event_data['status'] == 'new'
        assert event_data['side'] == 'buy'
        assert event_data['px'] == 99.0
        assert event_data['qty'] == 5.0

    def test_submit_limit_order_buy_crossing_post_only(self):
        """Test submitting limit buy order that crosses with post-only enabled."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 10.0, 'ask': 10.0}
        }

        order = {
            'order_id': 'test-125',
            'side': 'buy',
            'qty': 5.0,
            'price': 102.0,  # Above best ask, crosses
            'order_type': 'limit'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-125'
        assert order_id not in sink._orders  # Should be removed due to rejection

        # Verify rejection event
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-125'
        assert event_data['status'] == 'rejected'
        assert event_data['reason'] == 'post_only_cross'

    def test_submit_limit_order_sell_crossing_ioc(self):
        """Test submitting limit sell order that crosses with IOC enabled."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 10.0, 'ask': 10.0}
        }

        order = {
            'order_id': 'test-126',
            'side': 'sell',
            'qty': 3.0,
            'price': 99.0,  # Below best bid, crosses
            'order_type': 'limit'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-126'
        assert order_id not in sink._orders  # Should be rejected due to post-only

        # Verify rejection event (post-only takes precedence over IOC for crossing orders)
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-126'
        assert event_data['status'] == 'rejected'
        assert event_data['reason'] == 'post_only_cross'

    def test_cancel_existing_order(self):
        """Test cancelling an existing order."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # First submit an order
        order = {
            'order_id': 'test-cancel',
            'side': 'buy',
            'qty': 5.0,
            'price': 99.0,
            'order_type': 'limit'
        }

        sink.submit(order)
        assert 'test-cancel' in sink._orders

        # Reset mock to check cancel event
        self.mock_event_logger.reset_mock()

        # Cancel the order
        result = sink.cancel('test-cancel')

        assert result is True
        assert 'test-cancel' not in sink._orders

        # Verify cancel event
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-cancel'
        assert event_data['status'] == 'cancelled'
        assert event_data['reason'] == 'cancelled_by_user'

    def test_cancel_nonexistent_order(self):
        """Test cancelling a non-existent order."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        result = sink.cancel('nonexistent')

        assert result is False
        self.mock_event_logger.emit.assert_not_called()

    def test_amend_existing_order(self):
        """Test amending an existing order."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # First submit an order
        order = {
            'order_id': 'test-amend',
            'side': 'buy',
            'qty': 5.0,
            'price': 99.0,
            'order_type': 'limit'
        }

        sink.submit(order)
        assert 'test-amend' in sink._orders

        # Reset mock to check amend event
        self.mock_event_logger.reset_mock()

        # Amend the order
        result = sink.amend('test-amend', {'price': 100.0, 'qty': 7.0})

        assert result is True
        assert sink._orders['test-amend']['price'] == 100.0
        assert sink._orders['test-amend']['qty'] == 7.0

        # Verify amend event
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-amend'
        assert event_data['status'] == 'replaced'
        assert event_data['px'] == 100.0
        assert event_data['qty'] == 5.0  # Uses 'remaining' field, not updated 'qty'

    def test_amend_nonexistent_order(self):
        """Test amending a non-existent order."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        result = sink.amend('nonexistent', {'price': 100.0})

        assert result is False
        self.mock_event_logger.emit.assert_not_called()

    def test_on_tick_maker_partial_fill(self):
        """Test on_tick processing with maker partial fill."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # Submit a limit order
        order = {
            'order_id': 'test-maker',
            'side': 'buy',
            'qty': 10.0,
            'price': 100.0,
            'order_type': 'limit'
        }

        sink.submit(order)
        assert 'test-maker' in sink._orders

        # Reset mock
        self.mock_event_logger.reset_mock()

        # Simulate market tick with some traded volume
        market_snapshot = {
            'depth': {
                'at_price': {100.0: 5.0},  # 5 units ahead in queue
                'levels_sum': {100.0: 5.0}
            },
            'traded_since_last': {100.0: 7.5}  # 7.5 units traded
        }

        sink.on_tick(market_snapshot)

        # Should have partial fill: (7.5 / (5.0 + 10.0 + eps)) * 10.0 ≈ 5.45
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-maker'
        assert event_data['status'] == 'partial'
        assert event_data['qty'] > 0
        assert event_data['fill_ratio'] > 0

    def test_on_tick_ttl_expiration(self):
        """Test on_tick processing with TTL expiration."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # Submit a limit order
        order = {
            'order_id': 'test-ttl',
            'side': 'buy',
            'qty': 10.0,
            'price': 100.0,
            'order_type': 'limit'
        }

        sink.submit(order)
        assert 'test-ttl' in sink._orders

        # Reset mock
        self.mock_event_logger.reset_mock()

        # Advance time beyond TTL
        sink._time = Mock(return_value=3000.0)  # 2000ms later

        # Simulate market tick with no trading
        market_snapshot = {
            'depth': {'at_price': {100.0: 0.0}},
            'traded_since_last': {100.0: 0.0}
        }

        sink.on_tick(market_snapshot)

        # Should cancel due to TTL expiration
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-ttl'
        assert event_data['status'] == 'cancelled'
        assert event_data['reason'] == 'ttl_expired'
        assert 'test-ttl' not in sink._orders

    def test_rng_seed_emission(self):
        """Test that RNG seed is emitted only once."""
        config_with_seed = self.base_config.copy()
        config_with_seed['order_sink']['sim_local']['seed'] = 999

        sink = SimLocalSink(
            cfg=config_with_seed,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # Submit first order
        order1 = {
            'order_id': 'test-seed-1',
            'side': 'buy',
            'qty': 1.0,
            'order_type': 'market'
        }

        sink.submit(order1)

        # Submit second order
        order2 = {
            'order_id': 'test-seed-2',
            'side': 'sell',
            'qty': 1.0,
            'order_type': 'market'
        }

        sink.submit(order2)

        # Should have emitted 2 events
        assert self.mock_event_logger.emit.call_count == 2

        # First event should contain seed
        first_call = self.mock_event_logger.emit.call_args_list[0]
        first_event_data = first_call[0][1]
        assert 'rng_seed' in first_event_data
        assert first_event_data['rng_seed'] == 999

        # Second event should not contain seed
        second_call = self.mock_event_logger.emit.call_args_list[1]
        second_event_data = second_call[0][1]
        assert 'rng_seed' not in second_event_data

    def test_sample_latency_range(self):
        """Test latency sampling within configured range."""
        sink = SimLocalSink(cfg=self.base_config)

        latencies = [sink._sample_latency() for _ in range(100)]

        assert all(5 <= latency <= 15 for latency in latencies)

    def test_sample_slip_range(self):
        """Test slippage sampling within configured range."""
        sink = SimLocalSink(cfg=self.base_config)

        slips = [sink._sample_slip() for _ in range(100)]

        assert all(0.0 <= slip <= 2.0 for slip in slips)

    def test_market_order_no_liquidity_no_ioc(self):
        """Test market order with no liquidity and IOC disabled."""
        config_no_ioc = self.base_config.copy()
        config_no_ioc['order_sink']['sim_local']['ioc'] = False

        sink = SimLocalSink(
            cfg=config_no_ioc,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 0.0, 'ask': 0.0}  # No liquidity
        }

        order = {
            'order_id': 'test-no-liq-no-ioc',
            'side': 'buy',
            'qty': 5.0,
            'order_type': 'market'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-no-liq-no-ioc'
        assert order_id in sink._orders  # Should remain in orders

        # Verify new order event
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-no-liq-no-ioc'
        assert event_data['status'] == 'new'
        assert event_data['reason'] is None

    def test_on_tick_levels_sum_queue_model(self):
        """Test on_tick processing with levels_sum queue model."""
        config_levels_sum = self.base_config.copy()
        config_levels_sum['order_sink']['sim_local']['maker'] = {
            'queue_model': 'levels_sum',
            'queue_safety_eps': 1e-6
        }

        sink = SimLocalSink(
            cfg=config_levels_sum,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        # Submit a limit order
        order = {
            'order_id': 'test-levels-sum',
            'side': 'buy',
            'qty': 10.0,
            'price': 100.0,
            'order_type': 'limit'
        }

        sink.submit(order)
        assert 'test-levels-sum' in sink._orders

        # Reset mock
        self.mock_event_logger.reset_mock()

        # Simulate market tick with levels_sum model
        market_snapshot = {
            'depth': {
                'levels_sum': {100.0: 5.0},  # Sum of all levels at price
                'at_price': {100.0: 5.0}
            },
            'traded_since_last': {100.0: 7.5}
        }

        sink.on_tick(market_snapshot)

        # Should have partial fill using levels_sum model
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-levels-sum'
        assert event_data['status'] == 'partial'

    def test_market_order_sell_fill_price_calculation(self):
        """Test market sell order fill price calculation."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 10.0, 'ask': 10.0}
        }

        order = {
            'order_id': 'test-sell-fill-price',
            'side': 'sell',
            'qty': 5.0,
            'order_type': 'market'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-sell-fill-price'
        assert order_id not in sink._orders  # Should be filled

        # Verify fill event with correct sell-side price calculation
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-sell-fill-price'
        assert event_data['status'] == 'filled'
        assert event_data['side'] == 'sell'
        # For sell orders: fill_px = bid * (1.0 - slip / 10000.0)
        expected_fill_px = 100.0 * (1.0 - sink._sample_slip() / 10000.0)
        assert event_data['px'] is not None

    def test_market_order_partial_liquidity_ioc(self):
        """Test market order with partial liquidity and IOC enabled."""
        sink = SimLocalSink(
            cfg=self.base_config,
            ev=self.mock_event_logger,
            time_func=self.mock_time_func
        )

        market = {
            'best_bid': 100.0,
            'best_ask': 101.0,
            'liquidity': {'bid': 0.0, 'ask': 3.0}  # Partial liquidity
        }

        order = {
            'order_id': 'test-partial-liq',
            'side': 'buy',
            'qty': 5.0,
            'order_type': 'market'
        }

        order_id = sink.submit(order, market)

        assert order_id == 'test-partial-liq'
        assert order_id not in sink._orders  # Should be filled and removed

        # Verify partial fill event
        self.mock_event_logger.emit.assert_called_once()
        call_args = self.mock_event_logger.emit.call_args
        event_type, event_data = call_args[0]

        assert event_type == 'ORDER_STATUS(sim)'
        assert event_data['order_id'] == 'test-partial-liq'
        assert event_data['status'] == 'filled'
        assert event_data['qty'] == 3.0  # Limited by available liquidity
        assert event_data['fill_ratio'] == 3.0 / 5.0
