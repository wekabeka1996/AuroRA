from __future__ import annotations

import os
import json
from core.execution.sim_local_sink import SimLocalSink


def main():
    os.makedirs('logs', exist_ok=True)
    cfg = {'order_sink': {'sim_local': {'latency_ms_range': [1, 1], 'slip_bps_range': [1.0, 1.0]}}}
    market = {'best_bid': 99.0, 'best_ask': 101.0, 'liquidity': {'bid': 100.0, 'ask': 100.0}}

    sink_long = SimLocalSink(cfg)
    evs_long = []
    # collect events by temporarily hijacking logger
    orig = sink_long._ev.emit

    def collect_long(code, details=None, *a, **kw):
        evs_long.append(details or {})
        return orig(code, details or {}, *a, **kw)

    sink_long._ev.emit = collect_long
    sink_long.submit({'side': 'buy', 'qty': 1.0, 'order_type': 'market'}, market)
    sink_long._ev.emit = orig

    sink_short = SimLocalSink(cfg)
    evs_short = []
    orig2 = sink_short._ev.emit

    def collect_short(code, details=None, *a, **kw):
        evs_short.append(details or {})
        return orig2(code, details or {}, *a, **kw)

    sink_short._ev.emit = collect_short
    sink_short.submit({'side': 'sell', 'qty': 1.0, 'order_type': 'market'}, market)
    sink_short._ev.emit = orig2

    # find first filled event with tca
    def pick(evs):
        for d in evs:
            if d.get('status') == 'filled' and 'tca_breakdown' in d:
                return d
        return None

    l = pick(evs_long)
    s = pick(evs_short)
    outp = 'logs/tca_identity_check.txt'
    with open(outp, 'w', encoding='utf-8') as fh:
        if l:
            mid = (market['best_bid'] + market['best_ask']) / 2.0
            is_bps = ((l.get('px') - mid) / mid) * 10000.0 if mid else 0.0
            fh.write(f"LONG IS_bps={is_bps:.8f}\n")
            fh.write(json.dumps(l.get('tca_breakdown', {})) + '\n')
            fh.write(f"IDENTITY: {is_bps:.8f} = {sum(l.get('tca_breakdown', {}).values()):.8f}\n")
        if s:
            mid = (market['best_bid'] + market['best_ask']) / 2.0
            is_bps = ((s.get('px') - mid) / mid) * 10000.0 if mid else 0.0
            fh.write(f"SHORT IS_bps={is_bps:.8f}\n")
            fh.write(json.dumps(s.get('tca_breakdown', {})) + '\n')
            fh.write(f"IDENTITY: {is_bps:.8f} = {sum(s.get('tca_breakdown', {}).values()):.8f}\n")

    print('Wrote', outp)


if __name__ == '__main__':
    main()
