from __future__ import annotations
import os, json, math, argparse
from typing import Iterable


def _percentile(data: Iterable[float], p: float):
    arr = list(data)
    n = len(arr)
    if n == 0:
        return None
    arr.sort()
    if p <= 0:
        return arr[0]
    if p >= 100:
        return arr[-1]
    k = (n - 1) * (p / 100.0)
    f = math.floor(k); c = math.ceil(k)
    if f == c:
        return arr[int(k)]
    d0 = arr[f] * (c - k)
    d1 = arr[c] * (k - f)
    return d0 + d1


def compute_bridge_improvement_stats(bridges: list[dict], eps: float) -> dict:
    vals = [b.get('improvement', 0.0) for b in bridges if isinstance(b, dict)]
    count_all = len(vals)
    positive_mask = [v for v in vals if v >= eps]
    positive_fraction_eps = (len(positive_mask) / count_all) if count_all else 0.0
    mean_val = sum(vals) / count_all if count_all else 0.0
    p10 = _percentile(vals, 10.0)
    p50 = _percentile(vals, 50.0)
    p90 = _percentile(vals, 90.0)
    width = (p90 - p10) if (p90 is not None and p10 is not None) else None
    return {
        'count': count_all,
        'positive_fraction_eps': positive_fraction_eps,
        'mean': mean_val,
        'p10': p10,
        'p50': p50,
        'p90': p90,
        'width_p90_p10': width,
    }


def tally_blackbox_events(blackbox_path: str) -> dict:
    two_signals = mi_guard = reach_reject = 0
    last_tau_ema = None
    if not os.path.exists(blackbox_path):
        return {
            'two_signals_block_count': 0,
            'mi_guard_block_count': 0,
            'reachability_reject_count': 0,
            'tau_drift_ema': None,
        }
    with open(blackbox_path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
            et = ev.get('event')
            payload = ev.get('payload', {}) if isinstance(ev, dict) else {}
            if et == 'policy_block_two_signals':
                two_signals += 1
            elif et == 'policy_block_mi_guard':
                mi_guard += 1
            elif et == 'reachability_reject':
                reach_reject += 1
            elif et == 'tau_drift':
                if 'ema' in payload:
                    last_tau_ema = payload['ema']
    return {
        'two_signals_block_count': two_signals,
        'mi_guard_block_count': mi_guard,
        'reachability_reject_count': reach_reject,
        'tau_drift_ema': last_tau_ema,
    }


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument('--run-dir', required=True)
    ap.add_argument('--config', default='configs/r1.yaml')
    ap.add_argument('--out', default='summary_r1.json')
    return ap.parse_args()


def load_cfg(path: str):
    import yaml
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def main():
    args = parse_args()
    cfg = load_cfg(args.config)
    bridges_dir = os.path.join(args.run_dir, 'bridges')
    bridge_records = []
    if os.path.isdir(bridges_dir):
        for fn in os.listdir(bridges_dir):
            if not fn.endswith('.json'):
                continue
            try:
                with open(os.path.join(bridges_dir, fn), 'r', encoding='utf-8') as f:
                    bridge_records.append(json.load(f))
            except Exception:
                pass
    eps = cfg.get('r1', {}).get('improvement_eps_reporting', 5e-4)
    bridge_stats = compute_bridge_improvement_stats(bridge_records, eps)
    bb_path = os.path.join(args.run_dir, 'blackbox.jsonl')
    block_stats = tally_blackbox_events(bb_path)
    tau_limit = cfg.get('r1', {}).get('tau_drift_limit', 0.05)
    tau_ema = block_stats.get('tau_drift_ema')
    tau_ok = (tau_ema is None) or (tau_ema <= tau_limit)
    summary = {
        'r1': {
            'bridges': bridge_stats,
            'blocks': {
                'two_signals_block_count': block_stats['two_signals_block_count'],
                'mi_guard_block_count': block_stats['mi_guard_block_count'],
                'reachability_reject_count': block_stats['reachability_reject_count'],
            },
            'tau_drift_ema': tau_ema,
            'tau_drift_ok': tau_ok,
            'improvement_eps_reporting': eps,
        }
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))

if __name__ == '__main__':
    main()
