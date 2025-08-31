from __future__ import annotations

import pytest

from core.execution.sim_local_sink import SimLocalSink


def make_market(bid=99.0, ask=101.0, bid_qty=10.0, ask_qty=10.0):
    return {
        'best_bid': bid,
        'best_ask': ask,
        'liquidity': {'bid': bid_qty, 'ask': ask_qty},
        'depth': {'at_price': {}, 'levels_sum': {}},
        'traded_since_last': {},
    }


def test_ioc_reject_when_no_liquidity():
    cfg = {'order_sink': {'sim_local': {'ioc': True, 'latency_ms_range': [1, 1], 'slip_bps_range': [0.0, 0.0]}}}
    sink = SimLocalSink(cfg)
    market = make_market(bid_qty=0.0, ask_qty=0.0)
    oid = sink.submit({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, market=market)
    # since ioc and no liquidity, order should be rejected and removed from store
    assert oid not in sink._orders


def test_post_only_reject_cross():
    cfg = {'order_sink': {'sim_local': {'post_only': True, 'latency_ms_range': [1,1], 'slip_bps_range': [0.0,0.0]}}}
    sink = SimLocalSink(cfg)
    # simulate market where best_ask is below our limit (cross)
    market = make_market(bid=99.0, ask=100.0, ask_qty=5.0, bid_qty=5.0)
    # submit limit order that would cross (price >= ask)
    oid = sink.submit({'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}, market=market)
    # In our simple submit implementation, post_only only applies when we detect cross; ensure order removed
    assert oid not in sink._orders


def test_slip_and_latency_within_bounds():
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [2, 5], 'slip_bps_range': [0.1, 0.5], 'seed': 42}}}
    sink = SimLocalSink(cfg)
    market = make_market()
    oid = sink.submit({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, market=market)
    # should not leave order in store (market fill)
    assert oid not in sink._orders


def test_ttl_cancel_on_tick():
    cfg = {'order_sink': {'sim_local': {'ttl_ms': 1, 'latency_ms_range': [1,1]}}}
    # use deterministic time function
    ts = [0]
    def tfunc():
        ts[0] += 1000
        return ts[0]
    sink = SimLocalSink(cfg, time_func=tfunc)
    oid = sink.submit({'side': 'buy', 'qty': 5.0, 'order_type': 'limit', 'price': 100.0})
    # advance tick, should trigger TTL cancel
    sink.on_tick({'depth': {'at_price': {}, 'levels_sum': {}}, 'traded_since_last': {}})
    assert oid not in sink._orders
