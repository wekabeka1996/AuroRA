import argparse
import json
import math
import os
from statistics import mean, median


def parse_args():
    p = argparse.ArgumentParser(description="Summarize shadow run log (JSONL)")
    p.add_argument("logfile", help="Path to jsonl log from shadow_run")
    p.add_argument("--limit", type=int, default=0, help="Optional max number of lines to read (0=all)")
    return p.parse_args()


def read_lines(path, limit=0):
    with open(path, 'r', encoding='utf-8') as f:
        for i, line in enumerate(f):
            if limit and i >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def percentile(values, p):
    if not values:
        return float('nan')
    arr = sorted(values)
    k = (len(arr) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(arr) - 1)
    if f == c:
        return arr[f]
    return arr[f] + (arr[c] - arr[f]) * (k - f)


def mad(values):
    if not values:
        return float('nan')
    m = median(values)
    devs = [abs(v - m) for v in values]
    return median(devs)


def safe_mean(values):
    vals = [v for v in values if isinstance(v, (int, float)) and v == v]
    return mean(vals) if vals else float('nan')


def main():
    args = parse_args()
    latencies = []
    kappa = []
    regimes = []
    forecasts = []
    interval_widths = []
    flips = 0
    last_regime = None

    for row in read_lines(args.logfile, args.limit):
        latencies.append(row.get('latency_ms', float('nan')))
        kappa.append(row.get('kappa_plus', float('nan')))
        regimes.append(row.get('regime'))
        forecasts.append(row.get('forecast'))
        if isinstance(row.get('interval'), list) or isinstance(row.get('interval'), tuple):
            lo, hi = row['interval']
        else:
            lo, hi = row.get('interval_lower'), row.get('interval_upper')
        if lo is not None and hi is not None:
            interval_widths.append(hi - lo)
        if last_regime is not None and row.get('regime') is not None and row['regime'] != last_regime:
            flips += 1
        last_regime = row.get('regime')

    # Псевдо delta surprisal
    delta_surprisal = []
    for fval, w in zip(forecasts, interval_widths):
        if fval is None or w is None:
            continue
        delta_surprisal.append(abs(fval) / (abs(w) + 1e-6))

    result = {
        'count': len(latencies),
        'latency_mean_ms': safe_mean(latencies),
        'latency_p50_ms': percentile(latencies, 50),
        'latency_p90_ms': percentile(latencies, 90),
        'latency_p95_ms': percentile(latencies, 95),
        'latency_p99_ms': percentile(latencies, 99),
        'kappa_mean': safe_mean(kappa),
        'kappa_median': median(kappa) if kappa else float('nan'),
        'kappa_mad': mad(kappa),
        'regime_flips': flips,
        'regime_flip_rate_per_call': (flips / len(regimes)) if regimes else float('nan'),
        'interval_width_mean': safe_mean(interval_widths),
        'delta_surprisal_mean': safe_mean(delta_surprisal),
        'delta_surprisal_p95': percentile(delta_surprisal, 95) if delta_surprisal else float('nan'),
        'delta_surprisal_mad': mad(delta_surprisal),
    }

    print(json.dumps(result, indent=2))

if __name__ == '__main__':
    main()
