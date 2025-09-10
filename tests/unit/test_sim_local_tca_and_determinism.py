import json

from core.execution.sim_local_sink import SimLocalSink


def make_market(bid=99.0, ask=101.0, bid_qty=10.0, ask_qty=10.0):
    return {
        'best_bid': bid,
        'best_ask': ask,
        'liquidity': {'bid': bid_qty, 'ask': ask_qty},
    }


def collect_events_for_sink(sink, actions):
    """actions: list of tuples ('submit'|'on_tick'|'cancel', args)"""
    events = []
    # patch event logger to collect into list
    orig_emit = sink._ev.emit

    def _collector(code, details=None, *a, **kw):
        events.append((code, details or {}))
        return orig_emit(code, details or {}, *a, **kw)

    sink._ev.emit = _collector
    for act, args in actions:
        if act == 'submit':
            sink.submit(*args)
        elif act == 'on_tick':
            sink.on_tick(*args)
        elif act == 'cancel':
            sink.cancel(*args)
    # restore
    sink._ev.emit = orig_emit
    return events


def test_tca_identity_sum_long_short(tmp_path):
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [1.0, 1.0]}}}
    sink = SimLocalSink(cfg)
    # long (buy market) and short (sell market)
    market = make_market(bid=99.0, ask=101.0, bid_qty=100, ask_qty=100)

    # Long
    events_long = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, market))])
    # Short
    sink2 = SimLocalSink(cfg)
    events_short = collect_events_for_sink(sink2, [('submit', ({'side': 'sell', 'qty': 1.0, 'order_type': 'market'}, market))])

    # Find tca_breakdown in filled events
    def find_tca(evlist):
        for code, d in evlist:
            if code and 'tca_breakdown' in d:
                return d['tca_breakdown'], d.get('px'), d.get('side')
        return None, None, None

    tca_l, px_l, side_l = find_tca(events_long)
    tca_s, px_s, side_s = find_tca(events_short)
    assert tca_l is not None and tca_s is not None

    def is_identity(tca, px, market):
        mid = (market['best_bid'] + market['best_ask']) / 2.0
        is_bps = ((px - mid) / mid) * 10000.0 if mid else 0.0
        comp_sum = sum(tca[k] for k in ['Spread_bps', 'Latency_bps', 'Adverse_bps', 'Impact_bps', 'Fees_bps'])
        return is_bps, comp_sum

    is_l, sum_l = is_identity(tca_l, px_l, market)
    is_s, sum_s = is_identity(tca_s, px_s, market)

    # identity within tolerance
    assert abs(is_l - sum_l) <= 1e-6
    assert abs(is_s - sum_s) <= 1e-6

    # sign mirror: long should be +, short should be - (approx)
    assert is_l * is_s <= 0 or abs(is_l) == abs(is_s)

    # write an artifact with an example breakdown
    out = tmp_path / 'tca_identity_check.txt'
    with open(out, 'w', encoding='utf-8') as f:
        f.write(f'Long: is_bps={is_l}, breakdown={json.dumps(tca_l)}\n')
        f.write(f'Short: is_bps={is_s}, breakdown={json.dumps(tca_s)}\n')


def test_seed_determinism_repro():
    cfg = {'order_sink': {'sim_local': {'seed': 12345, 'latency_ms_range': [1, 2], 'slip_bps_range': [0.1, 0.2]}}}
    sink = SimLocalSink(cfg)
    sink2 = SimLocalSink(cfg)

    events1 = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])
    events2 = collect_events_for_sink(sink2, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])

    # Compare sequences of (status, qty, px, slip_bps, latency_ms_action)
    seq1 = [(d.get('status'), d.get('qty'), d.get('px'), d.get('slip_bps'), d.get('latency_ms_action')) for c, d in events1]
    seq2 = [(d.get('status'), d.get('qty'), d.get('px'), d.get('slip_bps'), d.get('latency_ms_action')) for c, d in events2]
    assert seq1 == seq2


def test_seed_none_is_nondeterministic():
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 3], 'slip_bps_range': [0.0, 2.0]}}}
    sink = SimLocalSink(cfg)
    sink2 = SimLocalSink(cfg)
    ev1 = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])
    ev2 = collect_events_for_sink(sink2, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])
    seq1 = [(d.get('latency_ms_action'), d.get('slip_bps')) for c, d in ev1]
    seq2 = [(d.get('latency_ms_action'), d.get('slip_bps')) for c, d in ev2]
    assert seq1 != seq2


def test_slippage_within_range():
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [0.5, 0.5], 'seed': 999}}}
    sink = SimLocalSink(cfg)
    ev = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])
    for c, d in ev:
        if 'slip_bps' in d and d['slip_bps'] is not None:
            assert 0.5 <= d['slip_bps'] <= 0.5


def test_latency_within_range():
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [2, 5], 'slip_bps_range': [0.0, 0.0], 'seed': 7}}}
    sink = SimLocalSink(cfg)
    ev = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, make_market()))])
    for c, d in ev:
        if 'latency_ms_action' in d and d['latency_ms_action'] is not None:
            assert 2 <= d['latency_ms_action'] <= 5
        if 'latency_ms_fill' in d and d['latency_ms_fill'] is not None:
            assert 2 <= d['latency_ms_fill'] <= 5


def test_post_only_cross_rejected():
    cfg = {'order_sink': {'sim_local': {'post_only': True, 'latency_ms_range': [1,1], 'slip_bps_range': [0.0,0.0]}}}
    sink = SimLocalSink(cfg)
    market = make_market(bid=90.0, ask=95.0)
    ev = collect_events_for_sink(sink, [('submit', ({'side': 'buy', 'qty': 1.0, 'order_type': 'limit', 'price': 100.0}, market))])
    # find rejected with reason post_only_cross
    found = False
    for c, d in ev:
        if d.get('status') in ('rejected', 'new') and d.get('reason') == 'post_only_cross':
            found = True
    assert found


def test_partial_fills_progress_queue():
    cfg = {'order_sink': {'sim_local': {'maker': {'queue_model': 'depth_l1'}, 'latency_ms_range': [1,1], 'slip_bps_range': [0.0,0.0]}}}
    sink = SimLocalSink(cfg)
    # submit limit order
    sink.submit({'side': 'buy', 'qty': 10.0, 'order_type': 'limit', 'price': 100.0})
    # feed incremental traded_since_last at same price
    ms = {'depth': {'at_price': {100.0: 5.0}}, 'traded_since_last': {100.0: 2.0}}
    ev1 = collect_events_for_sink(sink, [('on_tick', (ms,))])
    ms2 = {'depth': {'at_price': {100.0: 4.0}}, 'traded_since_last': {100.0: 3.0}}
    ev2 = collect_events_for_sink(sink, [('on_tick', (ms2,))])
    # Extract maker events (partial) and check fill_ratio monotonicity
    ratios = []
    for e in ev1 + ev2:
        code, d = e
        if d.get('status') in ('partial', 'filled'):
            ratios.append(d.get('fill_ratio', 0.0))
    assert len(ratios) >= 1
    assert all(ratios[i] <= ratios[i+1] for i in range(len(ratios)-1))


def test_ttl_expiry_cancelled():
    ts = [0]
    def tfunc():
        ts[0] += 1000
        return ts[0]
    cfg = {'order_sink': {'sim_local': {'ttl_ms': 1, 'latency_ms_range': [1,1]}}}
    sink = SimLocalSink(cfg, time_func=tfunc)
    sink.submit({'side': 'buy', 'qty': 5.0, 'order_type': 'limit', 'price': 100.0})
    ev = collect_events_for_sink(sink, [('on_tick', ({},),)])
    found = any(d.get('reason') == 'ttl_expired' for c, d in ev)
    assert found
