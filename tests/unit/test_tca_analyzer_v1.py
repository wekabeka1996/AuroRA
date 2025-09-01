"""
Unit Tests for TCA Analyzer v1 Compatibility
===========================================

Tests v1 fallback mechanism, legacy latency penalty calculation,
and error handling for missing TCA components.
"""

import pytest
import time
from unittest.mock import Mock, patch

from core.tca.tca_analyzer import TCAAnalyzer, OrderExecution, FillEvent
from core.tca.types import TCAMetrics


class TestTCAAnalyzerV1Compatibility:
    """Test TCA analyzer v1 fallback functionality."""
    
    @pytest.fixture
    def basic_analyzer(self):
        """Create basic TCA analyzer."""
        return TCAAnalyzer(adverse_window_s=1.0, mark_ref="mid")
    
    @pytest.fixture
    def sample_execution(self):
        """Create sample order execution."""
        fills = [
            FillEvent(
                ts_ns=int(time.time_ns()) + 1000000,  # 1ms after decision
                qty=100.0,
                price=50001.0,
                fee=0.5,
                liquidity_flag='T'
            )
        ]
        
        return OrderExecution(
            order_id="test_order_123",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=int(time.time_ns()) - 5000000,  # 5ms before decision
            decision_ts_ns=int(time.time_ns()),
            arrival_price=50000.0,
            arrival_spread_bps=2.0,
            latency_ms=10.0
        )
    
    def test_v2_analysis_success(self, basic_analyzer, sample_execution):
        """Test successful v2 analysis."""
        market_data = {
            "mid_price": 50000.0,
            "expected_edge_bps": 5.0,
            "latency_bps": 0.1,
            "kappa_bps_per_ms": 0.01
        }
        
        result = basic_analyzer.analyze_order(sample_execution, market_data)
        
        assert isinstance(result, TCAMetrics)
        assert result.symbol == "BTCUSDT"
        assert result.side == "BUY"
        assert result.filled_qty == 100.0
        assert result.raw_edge_bps == 5.0
        assert result.error_msg is None  # No fallback occurred
    
    def test_v1_fallback_on_exception(self, basic_analyzer, sample_execution):
        """Test v1 fallback when v2 analysis fails."""
        # Create market data that will cause v2 to fail
        market_data = {
            "expected_edge_bps": 3.0,
            "kappa_bps_per_ms": 0.02,
            "spread_bps": 2.5
        }
        
        # Mock _analyze_v2 to raise exception
        with patch.object(basic_analyzer, '_analyze_v2', side_effect=Exception("v2 failed")):
            result = basic_analyzer.analyze_order(sample_execution, market_data)
            
            assert isinstance(result, TCAMetrics)
            assert result.symbol == "BTCUSDT"
            assert result.raw_edge_bps == 3.0
            # Should use legacy latency penalty calculation
            expected_latency_penalty = sample_execution.latency_ms * 0.02  # 10ms * 0.02
            assert abs(result.latency_bps + expected_latency_penalty) < 0.001  # Canonical negative
    
    def test_v1_legacy_latency_penalty(self, basic_analyzer):
        """Test v1 legacy latency penalty calculation."""
        execution = OrderExecution(
            order_id="latency_test",
            symbol="ETHUSDT", 
            side="SELL",
            target_qty=50.0,
            fills=[],  # No fills
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()),
            arrival_price=3000.0,
            arrival_spread_bps=3.0,
            latency_ms=25.0  # High latency
        )
        
        market_data = {
            "expected_edge_bps": 2.0,
            "kappa_bps_per_ms": 0.05,  # High penalty
            "mid_price": 3000.0
        }
        
        # Force v1 analysis
        result = basic_analyzer._analyze_v1(execution, market_data)
        
        assert result.symbol == "ETHUSDT"
        assert result.side == "SELL"
        assert result.raw_edge_bps == 2.0
        
        # Legacy latency penalty: 25ms * 0.05 = 1.25 bps
        expected_penalty = 25.0 * 0.05
        assert abs(result.latency_bps + expected_penalty) < 0.001
        
        # Legacy implementation shortfall includes positive penalty
        assert result.implementation_shortfall_bps >= 2.0 + expected_penalty
    
    def test_v1_maker_taker_logic(self, basic_analyzer):
        """Test v1 simplified maker/taker logic."""
        # Execution with majority maker fills
        maker_fills = [
            FillEvent(ts_ns=int(time.time_ns()), qty=80.0, price=50000.0, fee=0.0, liquidity_flag='M'),
            FillEvent(ts_ns=int(time.time_ns()), qty=20.0, price=50001.0, fee=0.2, liquidity_flag='T')
        ]
        
        execution = OrderExecution(
            order_id="maker_test",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=100.0,
            fills=maker_fills,
            arrival_ts_ns=int(time.time_ns()),
            decision_ts_ns=int(time.time_ns()),
            arrival_price=50000.0,
            arrival_spread_bps=2.0,
            latency_ms=5.0
        )
        
        market_data = {"spread_bps": 2.0, "kappa_bps_per_ms": 0.01}
        
        result = basic_analyzer._analyze_v1(execution, market_data)
        
        # Should be treated as maker (80% maker fills)
        assert result.maker_fill_ratio == 0.8
        assert abs(result.taker_fill_ratio - 0.2) < 0.001  # Handle floating point precision
        assert result.slippage_in_bps == 0.0  # No slippage for maker
    
    def test_v1_error_handling_missing_attributes(self, basic_analyzer):
        """Test v1 error handling for missing execution attributes."""
        # Create minimal execution object missing some attributes
        execution = Mock()
        execution.side = "BUY"
        execution.symbol = "TESTCOIN"
        execution.order_id = "missing_attrs"
        # Missing: arrival_price, fills, latency_ms, etc.
        
        market_data = {"expected_edge_bps": 1.0}
        
        result = basic_analyzer._analyze_v1(execution, market_data)
        
        assert result.symbol == "TESTCOIN"
        assert result.side == "BUY"
        assert result.order_id == "missing_attrs"
        # Should use safe defaults
        assert result.arrival_price == 100.0
        assert result.filled_qty == 0.0
        assert result.fill_ratio == 0.0
    
    def test_minimal_fallback_on_total_failure(self, basic_analyzer):
        """Test minimal fallback when both v2 and v1 fail."""
        # Create completely invalid execution
        execution = "not_an_execution_object"
        market_data = {}
        
        # Mock both v2 and v1 to fail
        with patch.object(basic_analyzer, '_analyze_v2', side_effect=Exception("v2 failed")):
            with patch.object(basic_analyzer, '_analyze_v1', side_effect=Exception("v1 failed")):
                result = basic_analyzer.analyze_order(execution, market_data)
                
        assert isinstance(result, TCAMetrics)
        assert result.symbol == "ERROR"
        assert result.filled_qty == 0.0
        assert result.error_msg is not None
        assert "v1 failed" in result.error_msg  # Check that v1 failure message is present    def test_v1_timing_calculations(self, basic_analyzer):
        """Test v1 timing calculation safety."""
        base_time = int(time.time_ns())
        
        fills = [
            FillEvent(ts_ns=base_time + 2000000, qty=50.0, price=100.0, fee=0.1, liquidity_flag='T'),
            FillEvent(ts_ns=base_time + 5000000, qty=50.0, price=100.1, fee=0.1, liquidity_flag='T')
        ]
        
        execution = OrderExecution(
            order_id="timing_test",
            symbol="TIMECOIN",
            side="BUY",
            target_qty=100.0,
            fills=fills,
            arrival_ts_ns=base_time - 1000000,
            decision_ts_ns=base_time,
            arrival_price=100.0,
            arrival_spread_bps=1.0,
            latency_ms=15.0
        )
        
        result = basic_analyzer._analyze_v1(execution, {})
        
        # Time to first fill: 2ms
        assert abs(result.time_to_first_fill_ms - 2.0) < 0.1
        # Total execution time: 5ms  
        assert abs(result.total_execution_time_ms - 5.0) < 0.1
        assert result.first_fill_ts_ns == base_time + 2000000
        assert result.last_fill_ts_ns == base_time + 5000000
    
    def test_v1_fee_calculation_safety(self, basic_analyzer):
        """Test v1 fee calculation with edge cases."""
        # Test with zero filled quantity
        execution_no_fills = Mock()
        execution_no_fills.side = "BUY"
        execution_no_fills.symbol = "ZERO"
        execution_no_fills.order_id = "no_fills"
        execution_no_fills.fills = []
        execution_no_fills.target_qty = 100.0
        
        result = basic_analyzer._analyze_v1(execution_no_fills, {})
        assert result.fees_bps == 0.0
        assert result.filled_qty == 0.0
        
        # Test with zero arrival price
        execution_zero_price = Mock()
        execution_zero_price.side = "SELL"
        execution_zero_price.symbol = "ZEROPRICE"
        execution_zero_price.order_id = "zero_price"
        execution_zero_price.fills = [Mock(qty=10.0, fee=1.0)]
        execution_zero_price.arrival_price = 0.0
        execution_zero_price.target_qty = 10.0
        
        result = basic_analyzer._analyze_v1(execution_zero_price, {})
        assert result.fees_bps == 0.0  # Safe fallback
        assert result.arrival_price == 100.0  # Default price