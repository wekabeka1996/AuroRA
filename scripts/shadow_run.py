import argparse
import time
import json
import os
import sys
from datetime import datetime
from statistics import mean

try:
    import requests
except ImportError:
    print("[ERROR] Missing dependency 'requests'. Install with: pip install requests")
    sys.exit(1)

DEFAULT_ENDPOINT = "http://127.0.0.1:8000/predict"


def parse_args():
    p = argparse.ArgumentParser(description="Shadow runner for Aurora Trading API")
    p.add_argument("--endpoint", default=DEFAULT_ENDPOINT, help="Prediction endpoint URL")
    p.add_argument("--interval", type=float, default=2.0, help="Seconds between calls")
    p.add_argument("--duration", type=int, default=60, help="Total seconds to run (0 = infinite)")
    p.add_argument("--outdir", default="shadow_logs", help="Directory for JSONL logs")
    p.add_argument("--features", type=int, default=11, help="Number of feature elements to send (dummy random values)")
    return p.parse_args()


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def build_payload(n_features: int):
    # For now send zeros – server ignores real features (placeholder)
    return {"features": [0.0] * n_features}


def main():
    args = parse_args()
    ensure_dir(args.outdir)
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(args.outdir, f"pred_{ts}.jsonl")
    print(f"[INFO] Shadow run started. Logging to {log_path}")

    latencies = []
    kappa_vals = []
    regimes = []
    last_regime = None
    regime_flips = 0
    start = time.time()
    n = 0

    try:
        with open(log_path, 'a', encoding='utf-8') as f:
            while True:
                now = time.time()
                if args.duration > 0 and (now - start) >= args.duration:
                    print("[INFO] Duration reached. Stopping.")
                    break
                payload = build_payload(args.features)
                t0 = time.perf_counter()
                try:
                    r = requests.post(args.endpoint, json=payload, timeout=10)
                    elapsed_ms = (time.perf_counter() - t0) * 1000
                    if r.status_code == 200:
                        data = r.json()
                        # fallback if server didn't echo latency
                        data.setdefault('latency_ms', elapsed_ms)
                        data['ts'] = datetime.utcnow().isoformat()
                        f.write(json.dumps(data) + '\n')
                        f.flush()
                        latencies.append(data['latency_ms'])
                        kappa_vals.append(data.get('kappa_plus', float('nan')))
                        regime = data.get('regime')
                        regimes.append(regime)
                        if last_regime is not None and regime is not None and regime != last_regime:
                            regime_flips += 1
                        last_regime = regime
                        n += 1
                        if n % 10 == 0:
                            print(f"[PROGRESS] calls={n} avg_latency={mean(latencies):.1f}ms p95~{percentile(latencies,95):.1f}ms kappa_mean={safe_mean(kappa_vals):.3f} flips={regime_flips}")
                    else:
                        print(f"[WARN] status={r.status_code} body={r.text[:120]}")
                except Exception as e:
                    print(f"[ERROR] request failed: {e}")
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("[INFO] Interrupted by user.")

    summary = build_summary(latencies, kappa_vals, regimes, regime_flips, start, time.time())
    print("[SUMMARY]", json.dumps(summary, indent=2))
    with open(log_path + '.summary.json', 'w', encoding='utf-8') as sf:
        json.dump(summary, sf, indent=2)


def percentile(values, p):
    if not values:
        return float('nan')
    arr = sorted(values)
    k = (len(arr)-1) * (p/100)
    f = int(k)
    c = min(f+1, len(arr)-1)
    if f == c:
        return arr[f]
    return arr[f] + (arr[c]-arr[f]) * (k-f)


def safe_mean(values):
    vals = [v for v in values if isinstance(v,(int,float)) and v==v]
    return mean(vals) if vals else float('nan')


def build_summary(latencies, kappa_vals, regimes, regime_flips, t0, t1):
    duration = t1 - t0
    return {
        'total_calls': len(latencies),
        'duration_sec': duration,
        'latency_avg_ms': safe_mean(latencies),
        'latency_p95_ms': percentile(latencies, 95),
        'kappa_plus_mean': safe_mean(kappa_vals),
        'regime_flips': regime_flips,
        'regime_flip_rate_per_min': (regime_flips / (duration/60)) if duration>0 else None
    }

if __name__ == '__main__':
    main()
