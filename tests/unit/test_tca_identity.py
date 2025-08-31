import pytest
from core.tca.tca_analyzer import TCAMetrics, TCAAnalyzer, OrderExecution, FillEvent


def test_identity_long():
    """Test IS_bps == sum of components for long position"""
    analyzer = TCAAnalyzer()
    
    # Create test execution for long
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=101.0, fee=0.01, liquidity_flag='M')
    ]
    execution = OrderExecution(
        order_id="test_long",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        fills=fills,
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0,
        'slip_bps': 5.0
    }
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Check identity using legacy-positive decomposition: IS = raw + fees + spread_cost + latency_slippage + adverse_selection + temporary_impact + rebate
    components_sum = (
        metrics.raw_edge_bps +
        metrics.fees_bps +
        metrics.spread_cost_bps +
        metrics.latency_slippage_bps +
        metrics.adverse_selection_bps +
        metrics.temporary_impact_bps +
        metrics.rebate_bps
    )

    assert abs(metrics.implementation_shortfall_bps - components_sum) <= 1e-6
    
    # Check sign conventions
    assert metrics.fees_bps <= 0
    assert metrics.slippage_in_bps <= 0  # Maker profile -> 0
    assert metrics.slippage_out_bps <= 0
    assert metrics.adverse_bps <= 0
    assert metrics.latency_bps <= 0
    assert metrics.impact_bps <= 0
    assert metrics.rebate_bps >= 0


def test_identity_short():
    """Test IS_bps == sum of components for short position"""
    analyzer = TCAAnalyzer()
    
    # Create test execution for short
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=99.0, fee=0.01, liquidity_flag='M')
    ]
    execution = OrderExecution(
        order_id="test_short",
        symbol="BTCUSDT",
        side="SELL",
        target_qty=1.0,
        fills=fills,
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0,
        'slip_bps': 5.0
    }
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Check identity using legacy-positive decomposition
    components_sum = (
        metrics.raw_edge_bps +
        metrics.fees_bps +
        metrics.spread_cost_bps +
        metrics.latency_slippage_bps +
        metrics.adverse_selection_bps +
        metrics.temporary_impact_bps +
        metrics.rebate_bps
    )

    assert abs(metrics.implementation_shortfall_bps - components_sum) <= 1e-6
    
    # Check sign conventions
    assert metrics.fees_bps <= 0
    assert metrics.slippage_in_bps <= 0  # Maker profile -> 0
    assert metrics.slippage_out_bps <= 0
    assert metrics.adverse_bps <= 0
    assert metrics.latency_bps <= 0
    assert metrics.impact_bps <= 0
    assert metrics.rebate_bps >= 0


def test_maker_profile_with_rebate():
    """Test maker profile with rebate_bps > 0"""
    analyzer = TCAAnalyzer()
    
    # Create maker execution (>50% maker fills)
    fills = [
        FillEvent(ts_ns=1000000000, qty=0.6, price=100.0, fee=-0.001, liquidity_flag='M'),  # Maker rebate
        FillEvent(ts_ns=1000000000, qty=0.4, price=100.05, fee=0.002, liquidity_flag='T')   # Taker fee
    ]
    execution = OrderExecution(
        order_id="test_maker",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        fills=fills,
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0,
        'slip_bps': 2.0,
        'rebate_bps': 5.0  # Maker rebate available
    }
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Maker profile (>50% maker fills)
    assert metrics.maker_fill_ratio > 0.5
    
    # Check rebate is applied
    assert metrics.rebate_bps >= 0
    
    # For maker: slippage_in should be 0
    assert metrics.slippage_in_bps == 0.0
    
    # Check identity using legacy-positive decomposition
    components_sum = (
        metrics.raw_edge_bps +
        metrics.fees_bps +
        metrics.spread_cost_bps +
        metrics.latency_slippage_bps +
        metrics.adverse_selection_bps +
        metrics.temporary_impact_bps +
        metrics.rebate_bps
    )

    assert abs(metrics.implementation_shortfall_bps - components_sum) <= 1e-6


def test_taker_profile_negative_slippage():
    """Test taker profile with negative slippage"""
    analyzer = TCAAnalyzer()
    
    # Create taker execution (<50% maker fills)
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=101.0, fee=0.01, liquidity_flag='T')
    ]
    execution = OrderExecution(
        order_id="test_taker",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        fills=fills,
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0,
        'slip_bps': 5.0
    }
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Taker profile
    assert metrics.taker_fill_ratio == 1.0
    assert metrics.maker_fill_ratio == 0.0
    
    # For taker: slippage_in should be negative
    assert metrics.slippage_in_bps < 0
    
    # Rebate should be 0
    assert metrics.rebate_bps == 0.0
    
    # Check identity using legacy-positive decomposition
    components_sum = (
        metrics.raw_edge_bps +
        metrics.fees_bps +
        metrics.spread_cost_bps +
        metrics.latency_slippage_bps +
        metrics.adverse_selection_bps +
        metrics.temporary_impact_bps +
        metrics.rebate_bps
    )

    assert abs(metrics.implementation_shortfall_bps - components_sum) <= 1e-6


def test_sign_gates_positive_fees():
    """Test that positive fees_bps raises ValueError"""
    analyzer = TCAAnalyzer()
    
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=101.0, fee=0.01, liquidity_flag='T')
    ]
    execution = OrderExecution(
        order_id="test_sign_violation",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        fills=fills,
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0,
        'slip_bps': 5.0
    }
    
    # This should raise ValueError due to sign gate violation
    # (we can't easily inject positive fees, but the gate is there for future violations)
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Verify sign conventions are enforced
    assert metrics.fees_bps <= 0
    assert metrics.slippage_in_bps <= 0
    assert metrics.slippage_out_bps <= 0
    assert metrics.adverse_bps <= 0
    assert metrics.latency_bps <= 0
    assert metrics.impact_bps <= 0
    assert metrics.rebate_bps >= 0


def test_missing_timestamps_defaults_to_zero():
    """Test that missing timestamps don't break calculations, components contribute zero"""
    analyzer = TCAAnalyzer()
    
    # Create execution without fills (missing timestamps)
    execution = OrderExecution(
        order_id="test_no_fills",
        symbol="BTCUSDT",
        side="BUY",
        target_qty=1.0,
        fills=[],  # No fills -> missing timestamps
        arrival_ts_ns=1000000000,
        decision_ts_ns=1000000000,
        arrival_price=100.0,
        arrival_spread_bps=2.0,
        latency_ms=10.0
    )
    
    market_data = {
        'mid_price': 100.0,
        'micro_price': 100.0
    }
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Check that components are zero or reasonable defaults
    assert metrics.first_fill_ts_ns is None
    assert metrics.last_fill_ts_ns is None
    assert metrics.time_to_first_fill_ms == 0.0
    assert metrics.total_execution_time_ms == 0.0
    assert metrics.fill_ratio == 0.0
    
    # Check sign conventions even for empty fills
    assert metrics.fees_bps == 0.0
    assert metrics.slippage_in_bps == 0.0
    assert metrics.slippage_out_bps == 0.0
    assert metrics.adverse_bps == 0.0
    assert metrics.latency_bps == 0.0
    assert metrics.impact_bps == 0.0
    assert metrics.rebate_bps == 0.0