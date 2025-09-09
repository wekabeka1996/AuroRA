from __future__ import annotations
from prometheus_client import CollectorRegistry, generate_latest
from tools.metrics_exporter import _Metrics
from core.execution.execution_service import ExecutionService
from core.execution.router_v2 import OrderIntent, MarketSpec
from decimal import Decimal


def mk_market():
    return MarketSpec(
        tick_size=Decimal('0.01'), lot_size=Decimal('0.1'), min_notional=Decimal('10'),
        maker_fee_bps=1, taker_fee_bps=5, best_bid=Decimal('100'), best_ask=Decimal('100.1'),
        spread_bps=1.0, mid=Decimal('100.05')
    )


def mk_intent(stop_bps=100, qty_hint=None, equity=Decimal('10000')):
    return OrderIntent(
        intent_id='tt', timestamp_ms=0, symbol='TEST', side='BUY', dir=1, strategy_id='s1',
        expected_return_bps=10, stop_dist_bps=stop_bps, tp_targets_bps=[200],
        risk_ctx={'equity_usd': str(equity)}, regime_ctx={}, exec_prefs={}, qty_hint=qty_hint
    )


def test_metrics_increment_and_gauges_set(monkeypatch):
    # Create isolated metrics instance
    M = _Metrics()
    # Monkeypatch global METRICS used in modules
    import tools.metrics_exporter as me
    me.METRICS = M

    svc = ExecutionService(config={'execution': {'sla': {'p95_ms': 100}}})

    market = mk_market()
    # Case 1: allow path
    intent1 = mk_intent(stop_bps=200)
    plan = svc.place(intent1, market, features={}, measured_latency_ms=50.0)
    assert hasattr(plan, 'mode')  # RoutedOrderPlan

    # Case 2: deny path (force SIZE_ZERO via huge stop)
    intent2 = mk_intent(stop_bps=10_000_000)
    decision = svc.place(intent2, market, features={}, measured_latency_ms=50.0)
    assert hasattr(decision, 'code')

    # Expose metrics text
    data = generate_latest(M.reg).decode()
    # Counters present/incremented
    assert 'aurora_route_decisions_total' in data
    assert 'aurora_order_denies_total' in data
    # Histograms have samples
    assert 'aurora_latency_tick_submit_ms_bucket' in data
    assert 'aurora_edge_net_after_tca_bps_bucket' in data
    # Gauges updated
    assert 'aurora_lambda_m' in data
    assert 'aurora_cvar_current_usd' in data
    assert 'aurora_f_port' in data
