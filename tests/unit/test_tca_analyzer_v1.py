from __future__ import annotations

import pytest
from datetime import datetime
from core.tca.tca_analyzer import (
    TCAAnalyzer, OrderExecution, FillEvent, TCAMetrics
)


class TestTCAAnalyzer:
    """Unit tests for TCA Analyzer v1.0"""
    
    @pytest.fixture
    def analyzer(self) -> TCAAnalyzer:
        """Test TCA analyzer instance"""
        return TCAAnalyzer(adverse_window_s=1.0, mark_ref="micro")
    
    @pytest.fixture
    def sample_execution(self) -> OrderExecution:
        """Sample order execution for testing"""
        fills = [
            FillEvent(
                ts_ns=1000000000000,  # 1 second after decision
                qty=0.5,
                price=101.0,
                fee=0.005,
                liquidity_flag="M",
                order_id="order_1"
            ),
            FillEvent(
                ts_ns=1001000000000,  # 1.1 seconds after decision
                qty=0.5,
                price=101.5,
                fee=0.005,
                liquidity_flag="T",
                order_id="order_1"
            )
        ]
        
        return OrderExecution(
            order_id="test_order_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            fills=fills,
            arrival_ts_ns=999000000000,  # 0.1 seconds before decision
            decision_ts_ns=999900000000,
            arrival_price=100.0,
            arrival_spread_bps=200.0,
            latency_ms=15.0
        )
    
    @pytest.fixture
    def market_data(self) -> dict:
        """Sample market data"""
        return {
            'mid_price': 101.0,
            'micro_price': 100.8,
            'spread_bps': 200.0
        }
    
    def test_initialization(self, analyzer: TCAAnalyzer):
        """Test TCA analyzer initialization"""
        assert analyzer.adverse_window_s == 1.0
        assert analyzer.mark_ref == "micro"
    
    def test_vwap_calculation(self, sample_execution: OrderExecution):
        """Test VWAP calculation"""
        expected_vwap = (0.5 * 101.0 + 0.5 * 101.5) / 1.0
        assert sample_execution.vwap_fill == expected_vwap
    
    def test_fill_ratio_calculation(self, sample_execution: OrderExecution):
        """Test fill ratio calculation"""
        assert sample_execution.fill_ratio == 1.0
    
    def test_total_fees_calculation(self, sample_execution: OrderExecution):
        """Test total fees calculation"""
        assert sample_execution.total_fees == 0.01
    
    def test_execution_time_calculation(self, sample_execution: OrderExecution):
        """Test execution time calculation"""
        expected_time_ns = 1001000000000 - 999900000000  # 0.2 seconds
        assert sample_execution.execution_time_ns == expected_time_ns
    
    def test_implementation_shortfall_calculation(self, analyzer: TCAAnalyzer):
        """Test implementation shortfall calculation"""
        # Long position: arrival=100, vwap=101, fees=0.01
        # IS = (101-100)/100 * 1e4 + fees_bps = 100 + 1 = 101 bps
        is_bps = analyzer._calculate_implementation_shortfall(
            side_sign=1.0,  # Long
            arrival_price=100.0,
            vwap_fill=101.0,
            fees=0.01
        )
        
        expected_is = 100.0 + 1.0  # Price diff + fees in bps
        assert abs(is_bps - expected_is) < 0.01
    
    def test_short_implementation_shortfall(self, analyzer: TCAAnalyzer):
        """Test implementation shortfall for short positions"""
        # Short position: arrival=100, vwap=99, fees=0.01
        # IS = (-1) * (99-100)/100 * 1e4 + fees_bps = 100 + 1 = 101 bps
        is_bps = analyzer._calculate_implementation_shortfall(
            side_sign=-1.0,  # Short
            arrival_price=100.0,
            vwap_fill=99.0,
            fees=0.01
        )
        
        expected_is = 100.0 + 1.0
        assert abs(is_bps - expected_is) < 0.01
    
    def test_spread_cost_calculation(self, analyzer: TCAAnalyzer):
        """Test spread cost calculation"""
        # Long: vwap=101, mid=100.5
        # Spread cost = 1 * (101-100.5)/100.5 * 1e4 = 497.51 bps
        spread_bps = analyzer._calculate_spread_cost(
            side_sign=1.0,
            vwap_fill=101.0,
            mid_price=100.5
        )
        
        expected_spread = 1.0 * (101.0 - 100.5) / 100.5 * 1e4
        assert abs(spread_bps - expected_spread) < 0.01
    
    def test_latency_slippage_calculation(self, analyzer: TCAAnalyzer):
        """Test latency slippage calculation"""
        # Mid at decision = 100, mid at first fill = 100.2
        # Latency slippage = 1 * (100.2-100)/100 * 1e4 = 200 bps
        latency_bps = analyzer._calculate_latency_slippage(
            side_sign=1.0,
            mid_decision=100.0,
            mid_first_fill=100.2
        )
        
        expected_latency = 20.0
        assert abs(latency_bps - expected_latency) < 0.01
    
    def test_adverse_selection_calculation(self, analyzer: TCAAnalyzer):
        """Test adverse selection calculation"""
        # Mock market data with price movement
        market_data = {
            1000000000000: 101.0,  # At fill
            1001000000000 + int(1.0 * 1e9): 101.2  # 1 second after last fill
        }
        
        execution = OrderExecution(
            order_id="test_order",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            fills=[FillEvent(ts_ns=1000000000000, qty=1.0, price=101.0, fee=0.0, liquidity_flag="M", queue_pos=2)],
            arrival_ts_ns=999000000000,
            decision_ts_ns=999900000000,
            arrival_price=100.0,
            arrival_spread_bps=200.0,
            latency_ms=15.0
        )
        
        adverse_bps = analyzer._calculate_adverse_selection(
            execution, market_data, side_sign=1.0
        )
        
        # Should be positive for adverse movement
        assert adverse_bps >= 0
    
    def test_temporary_impact_calculation(self, analyzer: TCAAnalyzer):
        """Test temporary impact calculation"""
        is_bps = 150.0
        spread_bps = 50.0
        latency_bps = 30.0
        adverse_bps = 20.0
        
        impact_bps = analyzer._calculate_temporary_impact(
            is_bps, spread_bps, latency_bps, adverse_bps
        )
        
        expected_impact = is_bps - spread_bps - latency_bps - adverse_bps
        assert impact_bps == expected_impact
    
    def test_realized_spread_calculation(self, analyzer: TCAAnalyzer):
        """Test realized spread calculation"""
        realized_bps = analyzer._calculate_realized_spread(
            side_sign=1.0,
            vwap_fill=101.0,
            mid_last_fill=100.8
        )
        
        expected = 1.0 * (101.0 - 100.8) / 100.8 * 1e4
        assert abs(realized_bps - expected) < 0.01
    
    def test_effective_spread_calculation(self, analyzer: TCAAnalyzer):
        """Test effective spread calculation"""
        effective_bps = analyzer._calculate_effective_spread(
            side_sign=1.0,
            vwap_fill=101.0,
            mid_decision=100.0
        )
        
        expected = 1.0 * (101.0 - 100.0) / 100.0 * 1e4
        assert effective_bps == expected
    
    def test_complete_tca_analysis(self, analyzer: TCAAnalyzer, sample_execution: OrderExecution, market_data: dict):
        """Test complete TCA analysis"""
        metrics = analyzer.analyze_order(sample_execution, market_data)
        
        assert isinstance(metrics, TCAMetrics)
        assert metrics.symbol == "BTCUSDT"
        assert metrics.side == "BUY"
        assert metrics.order_id == "test_order_1"
        assert metrics.fill_ratio == 1.0
        assert metrics.implementation_shortfall_bps >= 0
        assert metrics.spread_cost_bps >= 0
        assert metrics.latency_slippage_bps >= 0
        assert metrics.adverse_selection_bps >= 0
        assert metrics.temporary_impact_bps >= 0
    
    def test_metrics_aggregation(self, analyzer: TCAAnalyzer):
        """Test TCA metrics aggregation"""
        # Create sample metrics
        metrics_list = [
            TCAMetrics(
                implementation_shortfall_bps=100.0,
                spread_cost_bps=50.0,
                latency_slippage_bps=30.0,
                adverse_selection_bps=20.0,
                temporary_impact_bps=0.0,
                arrival_price=100.0,
                vwap_fill=101.0,
                mid_at_decision=100.0,
                mid_at_first_fill=100.1,
                mid_at_last_fill=100.2,
                decision_latency_ms=15.0,
                time_to_first_fill_ms=100.0,
                total_execution_time_ms=200.0,
                fill_ratio=1.0,
                maker_fill_ratio=0.5,
                taker_fill_ratio=0.5,
                avg_queue_position=2.0,
                total_fees=0.01,
                fees_bps=10.0,
                realized_spread_bps=50.0,
                effective_spread_bps=100.0,
                symbol="BTCUSDT",
                side="BUY",
                order_id="order_1",
                analysis_ts_ns=1000000000
            ),
            TCAMetrics(
                implementation_shortfall_bps=120.0,
                spread_cost_bps=60.0,
                latency_slippage_bps=40.0,
                adverse_selection_bps=20.0,
                temporary_impact_bps=0.0,
                arrival_price=100.0,
                vwap_fill=101.2,
                mid_at_decision=100.0,
                mid_at_first_fill=100.1,
                mid_at_last_fill=100.2,
                decision_latency_ms=20.0,
                time_to_first_fill_ms=150.0,
                total_execution_time_ms=250.0,
                fill_ratio=1.0,
                maker_fill_ratio=0.6,
                taker_fill_ratio=0.4,
                avg_queue_position=1.5,
                total_fees=0.012,
                fees_bps=12.0,
                realized_spread_bps=60.0,
                effective_spread_bps=120.0,
                symbol="BTCUSDT",
                side="BUY",
                order_id="order_2",
                analysis_ts_ns=1000000000
            )
        ]
        
        aggregates = analyzer.aggregate_metrics(metrics_list, group_by="symbol")
        
        assert "BTCUSDT" in aggregates
        btc_agg = aggregates["BTCUSDT"]
        
        # Check averages
        expected_avg_is = (100.0 + 120.0) / 2
        assert btc_agg['avg_implementation_shortfall_bps'] == expected_avg_is
        
        expected_avg_spread = (50.0 + 60.0) / 2
        assert btc_agg['avg_spread_cost_bps'] == expected_avg_spread
        
        # Check percentiles
        assert btc_agg['p50_implementation_shortfall_bps'] == 110.0  # Median of [100, 120]
        assert btc_agg['total_orders'] == 2
    
    def test_empty_metrics_aggregation(self, analyzer: TCAAnalyzer):
        """Test aggregation with empty metrics list"""
        aggregates = analyzer.aggregate_metrics([])
        assert aggregates == {}
    
    def test_single_metric_aggregation(self, analyzer: TCAAnalyzer):
        """Test aggregation with single metric"""
        metrics = [TCAMetrics(
            implementation_shortfall_bps=100.0,
            spread_cost_bps=50.0,
            latency_slippage_bps=30.0,
            adverse_selection_bps=20.0,
            temporary_impact_bps=0.0,
            arrival_price=100.0,
            vwap_fill=101.0,
            mid_at_decision=100.0,
            mid_at_first_fill=100.1,
            mid_at_last_fill=100.2,
            decision_latency_ms=15.0,
            time_to_first_fill_ms=100.0,
            total_execution_time_ms=200.0,
            fill_ratio=1.0,
            maker_fill_ratio=0.5,
            taker_fill_ratio=0.5,
            avg_queue_position=2.0,
            total_fees=0.01,
            fees_bps=10.0,
            realized_spread_bps=50.0,
            effective_spread_bps=100.0,
            symbol="BTCUSDT",
            side="BUY",
            order_id="order_1",
            analysis_ts_ns=1000000000
        )]
        
        aggregates = analyzer.aggregate_metrics(metrics)
        
        assert len(aggregates) == 1
        assert "BTCUSDT" in aggregates
        btc_agg = aggregates["BTCUSDT"]
        assert btc_agg['total_orders'] == 1
        assert btc_agg['avg_implementation_shortfall_bps'] == 100.0