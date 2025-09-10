#!/usr/bin/env python
"""Hard Enable Decider

Reads:
  * gating log JSONL (each line: {"run_id":..., "metrics": {metric_name: {"state": "OK|WARN|...", "value": float}}})
  * DCTS audit JSON (var_ratio, counts.robust)
  * existing ci_thresholds.yaml
Computes per target metric stability statistics and promotes hard_enabled if all criteria satisfied:
  - min observations
  - warn rate <= max-warn-rate
  - delta p95-p10 <= max-delta-p95p10 (reduced volatility)
  - var_ratio_rb (from audit) <= max-var-ratio
Writes updated yaml and emits decision log JSONL with reasons.

Exit codes:
  0 - applied changes
  2 - dry-run only
  3 - fatal error (schema / IO)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
from typing import Any

import yaml

# ---------------- Helpers ----------------

def load_yaml(path: Path) -> dict[str, Any]:
    with path.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def write_yaml(path: Path, data: dict[str, Any]):
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=True)
    tmp.replace(path)

# ---------------- Core logic ----------------

def quantiles(values: list[float]):
    if not values:
        return float('nan'), float('nan')
    vs = sorted(values)
    def q(p: float):
        if not vs:
            return float('nan')
        k = (len(vs)-1)*p
        lo = math.floor(k); hi = math.ceil(k)
        if lo == hi:
            return vs[int(k)]
        return vs[lo] + (vs[hi]-vs[lo])*(k-lo)
    return q(0.95), q(0.10)


def analyze_metric(entries: list[dict[str, Any]], metric_key: str):
    values = [e['metrics'][metric_key]['value'] for e in entries if metric_key in e.get('metrics', {}) and isinstance(e['metrics'][metric_key].get('value'), (int,float))]
    states = [e['metrics'][metric_key].get('state') for e in entries if metric_key in e.get('metrics', {})]
    n = len(values)
    p95, p10 = quantiles(values)
    delta = p95 - p10 if (not math.isnan(p95) and not math.isnan(p10)) else float('nan')
    warn_count = sum(1 for s in states if s and s.upper().startswith('WARN'))
    warn_rate = warn_count / len(states) if states else float('nan')
    return {
        'n': n,
        'p95': p95,
        'p10': p10,
        'delta_p95_p10': delta,
        'warn_rate': warn_rate,
    }


def decide(args, thresholds: dict[str, Any], gating_entries: list[dict[str, Any]], audit: dict[str, Any]):
    decisions = []
    hard_meta = thresholds.setdefault('hard_meta', {})
    meta = thresholds.setdefault('meta', {})
    candidate_reasons = {}
    var_ratio_rb = audit.get('var_ratio_rb') or audit.get('var_ratio')
    # map logical metrics -> threshold keys and relation orientation for message
    targets = {
        'tvf2.dcts_robust': 'dcts_min',
        'ci.churn': 'max_churn_per_1k',
    }
    for metric_name, thr_key in targets.items():
        stats = analyze_metric(gating_entries, metric_name)
        reasons = []
        if stats['n'] >= args.min_observations:
            reasons.append(f"n>={args.min_observations}")
        else:
            reasons.append(f"n<{args.min_observations}")
        if not math.isnan(stats['warn_rate']) and stats['warn_rate'] <= args.max_warn_rate:
            reasons.append(f"warn_rate<={args.max_warn_rate}")
        else:
            reasons.append(f"warn_rate>{args.max_warn_rate}")
        if not math.isnan(stats['delta_p95_p10']) and stats['delta_p95_p10'] <= args.max_delta_p95p10:
            reasons.append(f"delta_p95p10<={args.max_delta_p95p10}")
        else:
            reasons.append(f"delta_p95p10>{args.max_delta_p95p10}")
        if var_ratio_rb is not None and var_ratio_rb <= args.max_var_ratio:
            reasons.append(f"var_ratio<={args.max_var_ratio}")
        elif var_ratio_rb is not None:
            reasons.append(f"var_ratio>{args.max_var_ratio}")
        # Decision: all positive conditions present
        enable = (
            stats['n'] >= args.min_observations and
            not math.isnan(stats['warn_rate']) and stats['warn_rate'] <= args.max_warn_rate and
            not math.isnan(stats['delta_p95_p10']) and stats['delta_p95_p10'] <= args.max_delta_p95p10 and
            (var_ratio_rb is None or var_ratio_rb <= args.max_var_ratio)
        )
        prev = hard_meta.get(thr_key, {}).get('hard_enabled', False)
        changed = (enable != prev)
        if enable:
            hard_meta[thr_key] = {
                **hard_meta.get(thr_key, {}),
                'hard_enabled': True,
                'hard_reason': ';'.join(reasons),
                'schema_version': 1,
                'window_n': stats['n'],
                'warn_rate_k': stats['warn_rate'],
                'p95_p10_delta': stats['delta_p95_p10'],
                'var_ratio_rb': var_ratio_rb,
                'hard_candidate': True,
                'reasons': reasons,
                'decided_by': 'decider',
                'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
            }
        else:
            # do not forcibly disable unless existed
            if prev and not enable:
                hard_meta[thr_key] = {
                    **hard_meta.get(thr_key, {}),
                    'hard_enabled': False,
                    'hard_reason': ';'.join(reasons),
                    'schema_version': 1,
                    'window_n': stats['n'],
                    'warn_rate_k': stats['warn_rate'],
                    'p95_p10_delta': stats['delta_p95_p10'],
                    'var_ratio_rb': var_ratio_rb,
                    'hard_candidate': True,
                    'reasons': reasons,
                    'decided_by': 'decider',
                    'timestamp': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
                }
        decisions.append({
            'metric': metric_name,
            'threshold_key': thr_key,
            'enable': enable,
            'prev': prev,
            'changed': changed,
            'stats': stats,
            'reasons': reasons,
        })
        candidate_reasons[thr_key] = reasons
    meta['hard_candidate_reasons'] = candidate_reasons
    meta['hard_enable_decider_ts'] = int(time.time())
    if var_ratio_rb is not None:
        meta['var_ratio_rb'] = var_ratio_rb
    return decisions

# ---------------- CLI ----------------

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--gating-log', required=True)
    p.add_argument('--audit-json', required=True)
    p.add_argument('--thresholds', default='configs/ci_thresholds.yaml')
    p.add_argument('--min-observations', type=int, default=20)
    p.add_argument('--max-delta-p95p10', type=float, default=0.07)
    p.add_argument('--max-warn-rate', type=float, default=0.05)
    p.add_argument('--max-var-ratio', type=float, default=0.85)
    p.add_argument('--out', required=True)
    p.add_argument('--decision-log', default='artifacts/ci/hard_enable_log.jsonl')
    p.add_argument('--dryrun', action='store_true')
    return p.parse_args()


def main():
    args = parse_args()
    try:
        gating_entries = []
        with open(args.gating_log, encoding='utf-8') as f:
            for line in f:
                line=line.strip()
                if not line: continue
                try:
                    gating_entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        audit = {}
        with open(args.audit_json,encoding='utf-8') as f:
            audit = json.load(f)
        thresholds = load_yaml(Path(args.thresholds))
        decisions = decide(args, thresholds, gating_entries, audit)
        # write decision log
        decision_path = Path(args.decision_log)
        decision_path.parent.mkdir(parents=True, exist_ok=True)
        with decision_path.open('a', encoding='utf-8') as df:
            for d in decisions:
                df.write(json.dumps(d)+'\n')
        # output yaml
        out_path = Path(args.out)
        if args.dryrun:
            # write to out but mark as dry
            thresholds.setdefault('meta', {})['dryrun'] = True
            write_yaml(out_path, thresholds)
            return 2
        else:
            write_yaml(out_path, thresholds)
            return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 3

if __name__ == '__main__':
    sys.exit(main())
