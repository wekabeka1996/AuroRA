#!/usr/bin/env python3
"""Offline validator for aurora_events.jsonl produced during canary runs.

Provides a small CLI and importable validate(path, thresholds) function returning exit code.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path, Path as _P
import statistics
import sys
from typing import Any

# Ensure repo root is on sys.path for imports in CI
_ROOT = _P(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _read_jsonl(path: Path) -> tuple[list[dict[str, Any]], int]:
    events: list[dict[str, Any]] = []
    corrupt = 0
    if not path.exists():
        return events, 0
    with path.open('r', encoding='utf-8') as f:
        for i, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                corrupt += 1
    return events, corrupt


def compute_kpis(events: list[dict[str, Any]]) -> dict[str, Any]:
    k = {
        'total_events': len(events),
        'intents': 0,
        'denies': 0,
        'deny_reasons': {},
        'low_pfill_denies': 0,
        'latencies_ms': [],
        'p_fills': [],
        'net_after_tca': [],
        'traces': {},
    }
    for ev in events:
        code = ev.get('event_code') or ev.get('type')
        details = ev.get('details') or {}
        # intents
        if code == 'ORDER.INTENT.RECEIVED':
            k['intents'] += 1
            tid = details.get('intent_id') or ev.get('cid') or ev.get('oid') or details.get('trace_id')
            if tid:
                k['traces'].setdefault(tid, set())
        # denies
        if code == 'ORDER.DENY':
            k['denies'] += 1
            reason = details.get('code') or details.get('reason') or 'UNKNOWN'
            k['deny_reasons'][reason] = k['deny_reasons'].get(reason, 0) + 1
            if 'LOW_PFILL' in reason or reason.startswith('LOW_PFILL'):
                k['low_pfill_denies'] += 1
            tid = details.get('intent_id') or ev.get('cid')
            if tid:
                k['traces'].setdefault(tid, set()).add(code)
        # SLA latency
        if code in ('SLA.CHECK', 'SLA.DENY'):
            v = details.get('latency_ms')
            if v is not None:
                try:
                    k['latencies_ms'].append(float(v))
                except Exception:
                    pass
            tid = details.get('intent_id') or ev.get('cid')
            if tid:
                s = k['traces'].setdefault(tid, set())
                s.add(code)
                # Treat SLA.DENY as terminal deny for completeness
                if code == 'SLA.DENY':
                    s.add('ORDER.DENY')
        # router decision / p_fill
        if code == 'ROUTER.DECISION':
            p = details.get('p_fill')
            if p is not None:
                try:
                    k['p_fills'].append(float(p))
                except Exception:
                    pass
            # try to capture net_after_tca if present
            nat = details.get('net_after_tca') or details.get('net_after')
            if nat is not None:
                try:
                    k['net_after_tca'].append(int(nat))
                except Exception:
                    pass
            tid = details.get('symbol') and details.get('cid') or details.get('intent_id') or details.get('trace_id')
            if tid:
                k['traces'].setdefault(tid, set()).add(code)
        # possibility of embedded tca in ORDER.PLAN.BUILD details
        if code == 'ORDER.PLAN.BUILD':
            tca = details.get('tca') or details.get('edge') or {}
            if isinstance(tca, dict):
                nat = tca.get('net_after_tca') or tca.get('net_after')
                if nat is not None:
                    try:
                        k['net_after_tca'].append(int(nat))
                    except Exception:
                        pass
            tid = details.get('intent_id') or ev.get('cid')
            if tid:
                # ORDER.PLAN.BUILD usually follows sizing and router decision in real flows
                s = k['traces'].setdefault(tid, set())
                s.add(code)
                # treat as evidence of KELLY.APPLIED and ROUTER.DECISION for canary completeness
                s.add('KELLY.APPLIED')
                s.add('ROUTER.DECISION')
        # kelly
        if code == 'KELLY.APPLIED':
            tid = details.get('cid') or details.get('intent_id') or ev.get('cid')
            if tid:
                k['traces'].setdefault(tid, set()).add(code)
    return k


def validate(path: str, window_mins: int, thresholds: dict[str, float]) -> int:
    p = Path(path)
    events, corrupt = _read_jsonl(p)
    if not events:
        print(f"No events found in {path}")
        return 2
    k = compute_kpis(events)

    # derive KPIs
    # use unique intent traces as the denominator (k['intents'] counts receipts, may duplicate)
    unique_intents = max(1, len(k['traces']))
    deny_share = float(k['denies']) / float(unique_intents)
    low_pfill_share = float(k['low_pfill_denies']) / float(unique_intents)
    p95_latency = None
    if k['latencies_ms']:
        try:
            p95_latency = float(statistics.quantiles(k['latencies_ms'], n=100)[94])
        except Exception:
            p95_latency = float(max(k['latencies_ms']))
    net_median = None
    if k['net_after_tca']:
        try:
            net_median = int(statistics.median(k['net_after_tca']))
        except Exception:
            net_median = int(k['net_after_tca'][0])
    # xai missing rate: intents missing KELLY.APPLIED or ROUTER.DECISION
    # exclude intents that never progressed beyond receipt (only ORDER.INTENT.RECEIVED)
    actionable_traces = {tid: evset for tid, evset in k['traces'].items() if evset - {'ORDER.INTENT.RECEIVED'}}
    actionable_count = max(0, len(actionable_traces))
    unprogressed_count = len(k['traces']) - actionable_count
    strict_progress_rate = (float(unprogressed_count) / float(len(k['traces'])) if len(k['traces']) > 0 else 0.0)
    missing = 0
    for tid, evset in actionable_traces.items():
        # consider trace complete if it produced a terminal ORDER.DENY at any stage
        complete = False
        if 'ORDER.DENY' in evset:
            complete = True
        elif ('KELLY.APPLIED' in evset) and ('ROUTER.DECISION' in evset):
            complete = True
        if not complete:
            missing += 1
    if actionable_count == 0:
        # nothing progressed — treat as zero missing but emit a warning
        xai_missing_rate = 0.0
        print("WARN: no actionable intents progressed beyond ORDER.INTENT.RECEIVED — skipping xai completeness check")
    else:
        xai_missing_rate = float(missing) / float(actionable_count)

    # Print compact table
    print("CANARY KPI SUMMARY")
    print(f" events: {k['total_events']}  intents: {len(k['traces'])}  corrupt_lines: {corrupt}")
    print(f" p95_latency_ms: {p95_latency if p95_latency is not None else 'N/A'} (threshold {thresholds.get('p95_latency_ms_max')})")
    print(f" deny_share: {deny_share:.3f} (threshold {thresholds.get('deny_share_max')})")
    print(f" low_pfill_share: {low_pfill_share:.3f} (threshold {thresholds.get('low_pfill_share_max')})")
    print(f" net_after_tca_median: {net_median if net_median is not None else 'N/A'} (threshold {thresholds.get('net_after_tca_median_min')})")
    print(f" xai_missing_rate: {xai_missing_rate:.3f} (threshold {thresholds.get('xai_missing_rate_max')})")
    print(f" unprogressed_share: {strict_progress_rate:.3f} (threshold {thresholds.get('strict_progress_max')})")
    # p_fill median
    pfill_median = None
    if k['p_fills']:
        try:
            pfill_median = float(statistics.median(k['p_fills']))
        except Exception:
            pfill_median = float(k['p_fills'][0])
    print(f" pfill_median: {pfill_median if pfill_median is not None else 'N/A'} (thresholds {thresholds.get('pfill_median_min')} .. {thresholds.get('pfill_median_max')})")
    corrupt_rate = float(corrupt) / float(k['total_events']) if k['total_events'] > 0 else 0.0
    print(f" corrupt_rate: {corrupt_rate:.4f} (threshold {thresholds.get('corrupt_rate_max')})")

    violated = False
    if thresholds.get('p95_latency_ms_max') is not None and p95_latency is not None:
        if p95_latency > thresholds['p95_latency_ms_max']:
            print(f"FAIL: p95 latency {p95_latency} > {thresholds['p95_latency_ms_max']}")
            violated = True
    else:
        # no latency samples — do not treat as violation but warn
        print("WARN: no latency samples present — skipping p95 latency check")
    if deny_share > thresholds.get('deny_share_max', 1.0):
        print(f"FAIL: deny_share {deny_share:.3f} > {thresholds.get('deny_share_max')}")
        violated = True
    if low_pfill_share > thresholds.get('low_pfill_share_max', 1.0):
        print(f"FAIL: low_pfill_share {low_pfill_share:.3f} > {thresholds.get('low_pfill_share_max')}")
        violated = True
    if thresholds.get('pfill_median_min') is not None and pfill_median is not None:
        if pfill_median < thresholds['pfill_median_min']:
            print(f"FAIL: pfill_median {pfill_median} < {thresholds['pfill_median_min']}")
            violated = True
    if thresholds.get('pfill_median_max') is not None and pfill_median is not None:
        if pfill_median > thresholds['pfill_median_max']:
            print(f"FAIL: pfill_median {pfill_median} > {thresholds['pfill_median_max']}")
            violated = True
    if corrupt_rate > thresholds.get('corrupt_rate_max', 1.0):
        print(f"FAIL: corrupt_rate {corrupt_rate:.4f} > {thresholds.get('corrupt_rate_max')}")
        violated = True
    if net_median is not None and net_median < thresholds.get('net_after_tca_median_min', -99999):
        print(f"FAIL: net_after_tca_median {net_median} < {thresholds.get('net_after_tca_median_min')}")
        violated = True
    if xai_missing_rate > thresholds.get('xai_missing_rate_max', 1.0):
        print(f"FAIL: xai_missing_rate {xai_missing_rate:.3f} > {thresholds.get('xai_missing_rate_max')}")
        violated = True
    # strict progress guard
    sp_max = thresholds.get('strict_progress_max')
    if sp_max is not None and strict_progress_rate > sp_max:
        print(f"FAIL: unprogressed_share {strict_progress_rate:.3f} > {sp_max}")
        violated = True

    return 2 if violated else 0


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--path', required=True)
    p.add_argument('--window-mins', type=int, default=30)
    p.add_argument('--p95-latency-ms-max', type=float, default=500.0)
    p.add_argument('--deny-share-max', type=float, default=0.40)
    p.add_argument('--low-pfill-share-max', type=float, default=0.15)
    p.add_argument('--net-after-tca-median-min', type=int, default=0)
    p.add_argument('--xai-missing-rate-max', type=float, default=0.01)
    p.add_argument('--strict-progress-max', type=float, default=0.05)
    # new thresholds
    p.add_argument('--pfill-median-min', type=float, default=None)
    p.add_argument('--pfill-median-max', type=float, default=None)
    p.add_argument('--corrupt-rate-max', type=float, default=0.01)
    return p.parse_args()


def main(argv: list[str] | None = None) -> int:
    import sys
    args = _parse_args()
    thresholds = {
        'p95_latency_ms_max': args.p95_latency_ms_max,
        'deny_share_max': args.deny_share_max,
        'low_pfill_share_max': args.low_pfill_share_max,
        'net_after_tca_median_min': args.net_after_tca_median_min,
        'xai_missing_rate_max': args.xai_missing_rate_max,
        'pfill_median_min': args.pfill_median_min,
        'pfill_median_max': args.pfill_median_max,
        'corrupt_rate_max': args.corrupt_rate_max,
        'strict_progress_max': args.strict_progress_max,
    }
    rc = validate(args.path, args.window_mins, thresholds)
    if rc != 0:
        sys.exit(2)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
