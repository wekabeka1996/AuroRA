from core.tca.tca_analyzer import TCAMetrics, TCAAnalyzer, OrderExecution, FillEvent


def test_backward_compat_old_args():
    """Test that old argument set doesn't break"""
    analyzer = TCAAnalyzer(adverse_window_s=2.0, mark_ref="mid")
    
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=101.0, fee=0.01, liquidity_flag='M')
    ]
    execution = OrderExecution(
        order_id="test_old",
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
    
    market_data = {'mid_price': 100.0}
    
    # Should not raise TypeError
    metrics = analyzer.analyze_order(execution, market_data)
    assert isinstance(metrics, TCAMetrics)


def test_extended_args_with_new_fields():
    """Test that extended argument set works and new fields are present"""
    analyzer = TCAAnalyzer(adverse_window_s=1.0, mark_ref="micro", extra_param="ignored")
    
    fills = [
        FillEvent(ts_ns=1000000000, qty=1.0, price=101.0, fee=0.01, liquidity_flag='M')
    ]
    execution = OrderExecution(
        order_id="test_extended",
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
    
    market_data = {'mid_price': 100.0, 'slip_bps': 5.0}
    
    metrics = analyzer.analyze_order(execution, market_data)
    
    # Check that all required fields are present
    required_fields = [
        'implementation_shortfall_bps', 'spread_cost_bps', 'latency_slippage_bps',
        'adverse_selection_bps', 'temporary_impact_bps', 'arrival_price', 'vwap_fill',
        'mid_at_decision', 'mid_at_first_fill', 'mid_at_last_fill', 'decision_latency_ms',
        'time_to_first_fill_ms', 'total_execution_time_ms', 'fill_ratio', 'maker_fill_ratio',
        'taker_fill_ratio', 'avg_queue_position', 'total_fees', 'fees_bps',
        'realized_spread_bps', 'effective_spread_bps', 'symbol', 'side', 'order_id',
        'arrival_ts_ns', 'analysis_ts_ns', 'decision_ts_ns', 'first_fill_ts_ns',
        'last_fill_ts_ns', 'order_qty', 'filled_qty', 'slip_bps'
    ]
    
    for field in required_fields:
        assert hasattr(metrics, field), f"Missing field: {field}"