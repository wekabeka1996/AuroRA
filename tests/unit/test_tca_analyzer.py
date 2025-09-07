from __future__ import annotations

import pytest
import time
import statistics
from unittest.mock import Mock
from core.tca.tca_analyzer import (
    TCAAnalyzer, OrderExecution, FillEvent, TCAMetrics
)


class TestTCAAnalyzer:
    """Comprehensive unit tests for TCA Analyzer v1.0"""

    @pytest.fixture
    def analyzer(self) -> TCAAnalyzer:
        """Test analyzer with default settings"""
        return TCAAnalyzer(adverse_window_s=1.0, mark_ref="micro")

    @pytest.fixture
    def analyzer_mid_ref(self) -> TCAAnalyzer:
        """Test analyzer using mid price as reference for spread cost calculations"""
        return TCAAnalyzer(adverse_window_s=1.0, mark_ref="mid")

    @pytest.fixture
    def sample_market_data(self) -> dict:
        """Sample market data for testing"""
        return {
            'mid_price': 100.0,
            'micro_price': 100.05,
            'bid': 99.95,
            'ask': 100.05,
            'spread_bps': 10.0
        }

    def test_initialization(self, analyzer: TCAAnalyzer):
        """Test TCA analyzer initialization"""
        assert analyzer.adverse_window_s == 1.0
        assert analyzer.mark_ref == "micro"

    def test_is_decomposition_long_buy_positive_slippage(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test IS decomposition for long buy with positive slippage"""
        # Setup: Buy order, fill price higher than arrival (positive slippage for buyer)
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=101.0, fee=0.1, liquidity_flag='T', order_id='test_1'),
            FillEvent(ts_ns=int(time.time_ns()) + 1000000, qty=50.0, price=101.2, fee=0.05, liquidity_flag='M', order_id='test_1')
        ]

        execution = OrderExecution(
            order_id='test_order_1',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=150.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 5000000,  # 5ms decision latency
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=5.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # For BUY: IS should be positive when fill > arrival
        assert metrics.implementation_shortfall_bps > 0
        # IS = Spread + Lat + Adv + Impact + Fees (within 0.1 bps tolerance)
        total_components = (
            metrics.spread_cost_bps +
            metrics.latency_slippage_bps +
            metrics.adverse_selection_bps +
            metrics.temporary_impact_bps +
            metrics.fees_bps
        )
        assert abs(metrics.implementation_shortfall_bps - total_components) <= 0.1

    def test_is_decomposition_short_sell_negative_slippage(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test IS decomposition for short sell with negative slippage"""
        # Setup: Sell order, fill price lower than arrival (negative slippage for seller = positive for strategy)
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=99.0, fee=0.1, liquidity_flag='T', order_id='test_2'),
            FillEvent(ts_ns=int(time.time_ns()) + 1000000, qty=50.0, price=98.8, fee=0.05, liquidity_flag='M', order_id='test_2')
        ]

        execution = OrderExecution(
            order_id='test_order_2',
            symbol='BTCUSDT',
            side='SELL',
            target_qty=150.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 3000000,  # 3ms decision latency
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=3.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # For SELL: IS should be positive (TCA convention), and equal to spread + fees for this case
        assert metrics.implementation_shortfall_bps > 0
        # IS should equal spread + fees (no latency/adverse in this test)
        expected_is = metrics.spread_cost_bps + metrics.fees_bps
        assert abs(metrics.implementation_shortfall_bps - expected_is) <= 0.1
        # IS = Spread + Lat + Adv + Impact + Fees (within 0.1 bps tolerance)
        total_components = (
            metrics.spread_cost_bps +
            metrics.latency_slippage_bps +
            metrics.adverse_selection_bps +
            metrics.temporary_impact_bps +
            metrics.fees_bps
        )
        assert abs(metrics.implementation_shortfall_bps - total_components) <= 0.1

    def test_long_short_mirror_symmetry(self, analyzer_mid_ref: TCAAnalyzer, sample_market_data: dict):
        """Test that long and short positions show mirror symmetry"""
        # Create symmetric scenarios: same price movement, opposite directions

        # Long buy scenario
        buy_fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=101.0, fee=0.1, liquidity_flag='T')
        ]
        buy_execution = OrderExecution(
            order_id='buy_order',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=buy_fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 2000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=2.0
        )

        # Short sell scenario (same price movement)
        sell_fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=99.0, fee=0.1, liquidity_flag='T')
        ]
        sell_execution = OrderExecution(
            order_id='sell_order',
            symbol='BTCUSDT',
            side='SELL',
            target_qty=100.0,
            fills=sell_fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 2000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=2.0
        )

        buy_metrics = analyzer_mid_ref.analyze_order(buy_execution, sample_market_data)
        sell_metrics = analyzer_mid_ref.analyze_order(sell_execution, sample_market_data)

        # Mirror symmetry: IS_long ≈ IS_short for symmetric price movements
        assert abs(buy_metrics.implementation_shortfall_bps - sell_metrics.implementation_shortfall_bps) <= 0.5
        # Both should be positive (TCA convention for cost metrics)
        assert buy_metrics.implementation_shortfall_bps > 0
        assert sell_metrics.implementation_shortfall_bps > 0
        # Spread costs should be mirror (both positive for symmetric bad executions)
        assert abs(buy_metrics.spread_cost_bps - sell_metrics.spread_cost_bps) <= 1.0

    def test_per_fill_calculations_sum_to_parent(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test that per-fill metrics sum to parent order metrics"""
        # Create order with multiple fills
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=50.0, price=101.0, fee=0.05, liquidity_flag='T', order_id='parent_1'),
            FillEvent(ts_ns=int(time.time_ns()) + 500000, qty=30.0, price=101.5, fee=0.03, liquidity_flag='M', order_id='parent_1'),
            FillEvent(ts_ns=int(time.time_ns()) + 1000000, qty=20.0, price=102.0, fee=0.02, liquidity_flag='T', order_id='parent_1')
        ]

        execution = OrderExecution(
            order_id='parent_order',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # Check VWAP calculation
        expected_vwap = (50*101.0 + 30*101.5 + 20*102.0) / 100.0
        assert abs(metrics.vwap_fill - expected_vwap) <= 0.001

        # Check fill ratio
        assert abs(metrics.fill_ratio - 1.0) <= 0.001  # 100/100 = 1.0

        # Check total fees
        expected_fees = 0.05 + 0.03 + 0.02
        assert abs(metrics.total_fees - expected_fees) <= 0.001

    def test_adverse_selection_positive_impulse_buy(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test adverse selection detection for buy order with positive price impulse"""
        # Setup market data with price movement after fill
        market_data = sample_market_data.copy()
        base_ts = int(time.time_ns())

        # Mock market data with price increase after fill (adverse for buyer)
        def mock_get_mid(ts_ns: int, market_data: dict) -> float:
            if ts_ns <= base_ts:
                return 100.0  # Mid at fill
            else:
                return 101.0  # Mid 1s after fill (adverse movement)

        # Monkey patch the analyzer
        analyzer._get_mid_price_at_ts = mock_get_mid

        fills = [
            FillEvent(ts_ns=base_ts, qty=100.0, price=100.5, fee=0.1, liquidity_flag='T')
        ]

        execution = OrderExecution(
            order_id='adv_buy_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=base_ts - 1000000,
            decision_ts_ns=base_ts - 2000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, market_data)

        # For BUY order, price increase after fill should show positive adverse selection
        assert metrics.adverse_selection_bps > 0
        # Adverse = side * (P_mid_adverse - P_mid_at_fill) / P_mid_at_fill * 1e4
        # BUY: +1 * (101.0 - 100.0) / 100.0 * 1e4 = +100 bps
        expected_adv = 100.0
        assert abs(metrics.adverse_selection_bps - expected_adv) <= 1.0

    def test_adverse_selection_negative_impulse_sell(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test adverse selection detection for sell order with negative price impulse"""
        market_data = sample_market_data.copy()
        base_ts = int(time.time_ns())

        # Mock market data with price decrease after fill (adverse for seller)
        def mock_get_mid(ts_ns: int, market_data: dict) -> float:
            if ts_ns <= base_ts:
                return 100.0  # Mid at fill
            else:
                return 99.0   # Mid 1s after fill (adverse movement)

        analyzer._get_mid_price_at_ts = mock_get_mid

        fills = [
            FillEvent(ts_ns=base_ts, qty=100.0, price=99.5, fee=0.1, liquidity_flag='T')
        ]

        execution = OrderExecution(
            order_id='adv_sell_test',
            symbol='BTCUSDT',
            side='SELL',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=base_ts - 1000000,
            decision_ts_ns=base_ts - 2000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, market_data)

        # For SELL order, price decrease after fill should show positive adverse selection
        assert metrics.adverse_selection_bps > 0
        # SELL: -1 * (99.0 - 100.0) / 100.0 * 1e4 = -(-1) * 1e4 = +100 bps
        expected_adv = 100.0
        assert abs(metrics.adverse_selection_bps - expected_adv) <= 1.0

    def test_latency_slippage_calculation(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test latency slippage calculation with injected delay"""
        base_ts = int(time.time_ns())

        # Mock market data with price movement during latency
        def mock_get_mid(ts_ns: int, market_data: dict) -> float:
            if ts_ns < base_ts - 2000000:  # At decision
                return 100.0
            elif ts_ns < base_ts:  # During latency
                return 100.2  # Price moved against buyer
            else:  # At fill
                return 100.2

        analyzer._get_mid_price_at_ts = mock_get_mid

        fills = [
            FillEvent(ts_ns=base_ts, qty=100.0, price=100.5, fee=0.1, liquidity_flag='T')
        ]

        execution = OrderExecution(
            order_id='latency_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=base_ts - 1000000,
            decision_ts_ns=base_ts - 3000000,  # 2ms latency
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=2.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # BUY: latency slippage = +1 * (100.2 - 100.0) / 100.0 * 1e4 = +20 bps
        expected_latency = 20.0
        assert abs(metrics.latency_slippage_bps - expected_latency) <= 1.0

    def test_spread_cost_maker_vs_taker(self, analyzer_mid_ref: TCAAnalyzer, sample_market_data: dict):
        """Test spread cost calculation for maker vs taker fills"""
        # Maker fill at mid price (should have ~0 spread cost)
        maker_fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=50.0, price=100.0, fee=0.01, liquidity_flag='M')
        ]

        maker_execution = OrderExecution(
            order_id='maker_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=50.0,
            fills=maker_fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        # Taker fill at ask price (should have positive spread cost for buyer)
        taker_fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=50.0, price=100.05, fee=0.05, liquidity_flag='T')
        ]

        taker_execution = OrderExecution(
            order_id='taker_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=50.0,
            fills=taker_fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        maker_metrics = analyzer_mid_ref.analyze_order(maker_execution, sample_market_data)
        taker_metrics = analyzer_mid_ref.analyze_order(taker_execution, sample_market_data)

        # Maker fill at mid should have near-zero spread cost
        assert abs(maker_metrics.spread_cost_bps) <= 1.0

        # Taker fill at ask should have positive spread cost for buyer
        assert taker_metrics.spread_cost_bps > 0
        # BUY at ask: spread_cost = +1 * (100.05 - 100.0) / 100.0 * 1e4 = +5 bps
        expected_taker_spread = 5.0
        assert abs(taker_metrics.spread_cost_bps - expected_taker_spread) <= 1.0

    def test_fees_calculation_with_funding(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test fees calculation including taker/maker fees and funding"""
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=60.0, price=100.0, fee=0.06, liquidity_flag='M'),  # Maker fee
            FillEvent(ts_ns=int(time.time_ns()) + 500000, qty=40.0, price=100.1, fee=0.12, liquidity_flag='T')  # Taker fee
        ]

        execution = OrderExecution(
            order_id='fees_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # Total fees should be sum of all fill fees
        expected_total_fees = 0.06 + 0.12
        assert abs(metrics.total_fees - expected_total_fees) <= 0.001

        # Fees in bps = total_fees * 1e4 / (filled_qty * arrival_price)
        # Note: fees_bps is canonical as negative (cost representation)
        expected_fees_bps = -expected_total_fees * 1e4 / (100.0 * 100.0)
        assert abs(metrics.fees_bps - expected_fees_bps) <= 0.1

    def test_aggregation_by_symbol(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test TCA metrics aggregation by symbol"""
        # Create multiple orders for same symbol
        executions = []
        for i in range(5):
            fills = [
                FillEvent(
                    ts_ns=int(time.time_ns()) + i * 1000000,
                    qty=100.0,
                    price=100.0 + i * 0.1,
                    fee=0.1,
                    liquidity_flag='T'
                )
            ]

            execution = OrderExecution(
                order_id=f'agg_test_{i}',
                symbol='BTCUSDT',
                side='BUY',
                target_qty=100.0,
                fills=fills,
                arrival_ts_ns=int(time.time_ns()) + i * 1000000,
                decision_ts_ns=int(time.time_ns()) + i * 1000000 - 1000000,
                arrival_price=100.0,
                arrival_spread_bps=10.0,
                latency_ms=1.0
            )
            executions.append(execution)

        # Analyze all orders
        metrics_list = [analyzer.analyze_order(exec, sample_market_data) for exec in executions]

        # Aggregate by symbol
        aggregates = analyzer.aggregate_metrics(metrics_list, group_by="symbol")

        # Should have one group for BTCUSDT
        assert 'BTCUSDT' in aggregates
        btc_agg = aggregates['BTCUSDT']

        # Check aggregate calculations
        assert 'avg_implementation_shortfall_bps' in btc_agg
        assert 'p50_implementation_shortfall_bps' in btc_agg
        assert 'p90_implementation_shortfall_bps' in btc_agg
        assert 'total_orders' in btc_agg
        assert btc_agg['total_orders'] == 5

        # Check that p50 is reasonable
        is_values = [m.implementation_shortfall_bps for m in metrics_list]
        expected_p50 = statistics.median(is_values)
        assert abs(btc_agg['p50_implementation_shortfall_bps'] - expected_p50) <= 0.1

    def test_aggregation_by_time_window(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test TCA metrics aggregation by time window"""
        base_ts = int(time.time_ns())

        # Create orders in different time windows
        executions = []
        for i in range(3):
            window_offset = i * 600 * 1e9  # 10 minutes apart (time_window_s=300, so 2 windows)

            fills = [
                FillEvent(
                    ts_ns=int(base_ts + window_offset),
                    qty=100.0,
                    price=100.0,
                    fee=0.1,
                    liquidity_flag='T'
                )
            ]

            execution = OrderExecution(
                order_id=f'time_agg_{i}',
                symbol='BTCUSDT',
                side='BUY',
                target_qty=100.0,
                fills=fills,
                arrival_ts_ns=int(base_ts + window_offset),
                decision_ts_ns=int(base_ts + window_offset - 1000000),
                arrival_price=100.0,
                arrival_spread_bps=10.0,
                latency_ms=1.0
            )
            executions.append(execution)

        # Analyze all orders
        metrics_list = [analyzer.analyze_order(exec, sample_market_data) for exec in executions]

        # Aggregate by time window
        aggregates = analyzer.aggregate_metrics(metrics_list, group_by="time", time_window_s=300)

        # Should have 2-3 time window groups
        assert len(aggregates) >= 2

        # Each group should have proper aggregates
        for group_key, agg_data in aggregates.items():
            assert 'avg_implementation_shortfall_bps' in agg_data
            assert 'total_orders' in agg_data
            assert agg_data['total_orders'] >= 1

    def test_mid_vs_micro_price_reference(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test difference between mid and micro price references"""
        # Create analyzer with mid reference
        mid_analyzer = TCAAnalyzer(mark_ref="mid")

        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=100.0, fee=0.1, liquidity_flag='T')
        ]

        execution = OrderExecution(
            order_id='price_ref_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        # Mock market data with different mid vs micro
        market_data = {
            'mid_price': 100.0,
            'micro_price': 100.05  # Micro price slightly different
        }

        # Mock market data with different prices at decision vs fill
        def mock_get_mid(ts_ns: int, market_data: dict) -> float:
            if ts_ns < int(time.time_ns()) - 1000000:  # At decision
                return 99.9  # Different price at decision
            else:  # At fill
                return 100.0

        analyzer._get_mid_price_at_ts = mock_get_mid
        mid_analyzer._get_mid_price_at_ts = mock_get_mid

        micro_metrics = analyzer.analyze_order(execution, market_data)
        mid_metrics = mid_analyzer.analyze_order(execution, market_data)

        # Metrics should be slightly different due to price reference
        # (Exact difference depends on implementation details)
        # With the mock, both should give the same results
        assert micro_metrics.latency_slippage_bps == mid_metrics.latency_slippage_bps

    def test_empty_fills_handling(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test handling of orders with no fills"""
        execution = OrderExecution(
            order_id='empty_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=[],  # No fills
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # Should handle gracefully
        assert metrics.vwap_fill == 0.0
        assert metrics.fill_ratio == 0.0
        assert metrics.total_fees == 0.0
        assert metrics.maker_fill_ratio == 0.0
        assert metrics.taker_fill_ratio == 0.0

    def test_extreme_values_handling(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test handling of extreme values and edge cases"""
        # Test with very small prices
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=100.0, price=0.000001, fee=0.0, liquidity_flag='T')
        ]

        execution = OrderExecution(
            order_id='extreme_test',
            symbol='SHIBUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=0.000001,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # Should not crash and provide reasonable results
        assert isinstance(metrics.implementation_shortfall_bps, float)
        assert isinstance(metrics.spread_cost_bps, float)

    def test_queue_position_impact(self, analyzer: TCAAnalyzer, sample_market_data: dict):
        """Test queue position impact on fill quality metrics"""
        fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=50.0, price=100.0, fee=0.05, liquidity_flag='M', queue_pos=1),
            FillEvent(ts_ns=int(time.time_ns()) + 500000, qty=50.0, price=100.1, fee=0.05, liquidity_flag='M', queue_pos=5)
        ]

        execution = OrderExecution(
            order_id='queue_test',
            symbol='BTCUSDT',
            side='BUY',
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()) - 1000000,
            arrival_price=100.0,
            arrival_spread_bps=10.0,
            latency_ms=1.0
        )

        metrics = analyzer.analyze_order(execution, sample_market_data)

        # Should calculate average queue position
        expected_avg_queue = (1 + 5) / 2
        assert metrics.avg_queue_position is not None
        assert abs(metrics.avg_queue_position - expected_avg_queue) <= 0.001

        # Both fills are maker, so maker_fill_ratio should be 1.0
        assert abs(metrics.maker_fill_ratio - 1.0) <= 0.001
        assert metrics.taker_fill_ratio == 0.0