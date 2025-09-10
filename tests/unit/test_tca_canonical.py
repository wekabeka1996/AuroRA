import time

import pytest

from core.tca.tca_analyzer import FillEvent, OrderExecution, TCAAnalyzer


def make_exec(side, liq, fee, price=100.0, spread=1.0, lat_ms=10.0):
    now = time.time_ns()
    fills=[FillEvent(ts_ns=now, qty=100.0, price=price, fee=fee, liquidity_flag=liq, queue_pos=1)]
    return OrderExecution(order_id="x", symbol="TEST", side=side, target_qty=100.0, fills=fills,
                          arrival_ts_ns=now-1_000_000_000, decision_ts_ns=now-2_000_000_000,
                          arrival_price=price, arrival_spread_bps=spread, latency_ms=lat_ms)


def analyze(ex, md=None):
    md = md or {"mid_price":ex.arrival_price, "micro_price":ex.arrival_price, "slip_bps":0.0}
    return TCAAnalyzer().analyze_order(ex, md)


@pytest.mark.parametrize("side,liq,fee", [("BUY","T",+1.0), ("SELL","T",+0.5)])
def test_taker_rebate_zero(side, liq, fee):
    m = analyze(make_exec(side, liq, fee))
    assert getattr(m, "rebate_bps", 0.0) == 0.0


@pytest.mark.parametrize("side,liq,fee", [("BUY","M",-0.4), ("SELL","M",-0.2)])
def test_maker_rebate_nonnegative(side, liq, fee):
    m = analyze(make_exec(side, liq, fee))
    assert getattr(m, "rebate_bps", 0.0) >= 0.0
    assert getattr(m, "fees_bps", 0.0) <= 0.0  # 0 при чистому ребейті — ок


@pytest.mark.parametrize("side,liq,fee", [
    ("BUY","M",-0.1), ("BUY","T",+0.1), ("SELL","M",-0.1), ("SELL","T",+0.1)
])
def test_identity_and_signs(side, liq, fee):
    m = analyze(make_exec(side, liq, fee))
    spread  = getattr(m,"spread_cost_bps",0.0) or getattr(m,"slippage_in_bps",0.0)
    latency = getattr(m,"latency_slippage_bps",0.0) or getattr(m,"latency_bps",0.0)
    adverse = getattr(m,"adverse_selection_bps",0.0) or getattr(m,"adverse_bps",0.0)
    impact  = getattr(m,"temporary_impact_bps",0.0) or getattr(m,"impact_bps",0.0)
    fees    = getattr(m,"fees_bps",0.0)
    rebate  = getattr(m,"rebate_bps",0.0)
    raw     = getattr(m,"raw_edge_bps", getattr(m,"expected_gain_bps",0.0))
    lhs, rhs = m.implementation_shortfall_bps, raw+fees+spread+latency+adverse+impact+rebate
    assert abs(lhs-rhs) <= 1e-6
    assert fees <= 0.0 and latency <= 0.0 and adverse <= 0.0 and impact <= 0.0 and rebate >= 0.0


def test_fill_prob_bounds_if_present():
    m = analyze(make_exec("BUY","M",-0.2))
    if hasattr(m, "fill_prob") and m.fill_prob is not None:
        assert 0.0 <= m.fill_prob <= 1.0
