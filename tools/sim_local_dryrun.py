from __future__ import annotations

import os
import random
import time
import statistics
import json
from core.execution.sim_local_sink import SimLocalSink


def run_dryrun(n_orders=500, seed=123, speedup=10):
    os.makedirs('reports', exist_ok=True)
    os.makedirs('logs', exist_ok=True)
    cfg = {'order_sink': {'sim_local': {'seed': seed, 'latency_ms_range': [1, 50], 'slip_bps_range': [0.0, 2.0]}}}
    sink = SimLocalSink(cfg)

    events = []
    # hijack emit
    orig = sink._ev.emit

    def collect(code, details=None, *a, **kw):
        events.append(details or {})
        return orig(code, details or {}, *a, **kw)

    sink._ev.emit = collect

    start = time.time()
    for i in range(n_orders):
        side = random.choice(['buy', 'sell'])
        order_type = 'market' if random.random() < 0.4 else 'limit'
        qty = round(random.uniform(0.5, 5.0), 3)
        if order_type == 'market':
            sink.submit({'side': side, 'qty': qty, 'order_type': 'market'}, market={'best_bid': 100.0, 'best_ask': 101.0, 'liquidity': {'bid': 100, 'ask': 100}})
        else:
            sink.submit({'side': side, 'qty': qty, 'order_type': 'limit', 'price': 100.0 + random.randint(-2, 2)})
        # simulate time passing (speedup factor)
        time.sleep(0.001)

    duration = time.time() - start
    sink._ev.emit = orig

    # compute metrics
    total = 0
    filled = 0
    canceled = 0
    rejected = 0
    fill_ratios = []
    is_vals = []
    latencies = []

    for d in events:
        total += 1
        st = d.get('status')
        if st in ('filled', 'FILLED'):
            filled += 1
            fill_ratios.append(d.get('fill_ratio', 1.0))
            if 'tca_breakdown' in d:
                t = d['tca_breakdown']
                is_vals.append(sum(t.values()))
        if st in ('cancelled', 'CANCELLED') and d.get('reason') == 'ttl_expired':
            canceled += 1
        if st in ('rejected', 'REJECTED'):
            rejected += 1
        if d.get('latency_ms_action') is not None:
            latencies.append(d.get('latency_ms_action'))

    trades_per_min = filled / max(1e-6, duration) * 60.0
    fill_ratio = statistics.mean(fill_ratios) if fill_ratios else 0.0
    median_is = statistics.median(is_vals) if is_vals else 0.0
    p90_is = (sorted(is_vals)[int(0.9 * len(is_vals))]) if is_vals else 0.0
    sla_breach = sum(1 for l in latencies if l > 100) / max(1, len(latencies))
    deny_rate = rejected / max(1, total)

    metrics = {
        'duration_s': duration,
        'n_orders': n_orders,
        'trades_per_min': trades_per_min,
        'fill_ratio': fill_ratio,
        'median_IS_bps': median_is,
        'p90_IS_bps': p90_is,
        'SLA_breach': sla_breach,
        'DenyRate': deny_rate,
    }

    with open('reports/sim_local_metrics.json', 'w', encoding='utf-8') as fh:
        json.dump(metrics, fh, indent=2)

    verdict = 'NO-GO'
    # simple economic proxy: median_IS >= 0 considered acceptable here (placeholder)
    if metrics['median_IS_bps'] >= 0 and metrics['SLA_breach'] <= 0.01 and metrics['DenyRate'] <= 0.30:
        verdict = 'GO'

    with open('reports/sim_local_summary.md', 'w', encoding='utf-8') as fh:
        fh.write('# Sim Local Dry-run Summary\n\n')
        fh.write('Metrics:\n')
        json.dump(metrics, fh, indent=2)
        fh.write('\n\n')
        fh.write('\nVerdict: **{}**\n'.format(verdict))

    print('Wrote reports/sim_local_metrics.json and reports/sim_local_summary.md')


if __name__ == '__main__':
    run_dryrun(n_orders=500)
