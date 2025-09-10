#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import Counter
import gzip
import json
from pathlib import Path
import time
from typing import Any

from core.lifecycle_correlation import LifecycleCorrelator

ROOT = Path(__file__).resolve().parents[1]


def _read_text_maybe_gz(p: Path) -> str:
    try:
        if p.suffix.endswith('.gz') or str(p).endswith('.gz'):
            with gzip.open(p, 'rt', encoding='utf-8') as f:
                return f.read()
        return p.read_text(encoding='utf-8')
    except Exception:
        return ''


def load_jsonl(path: Path):
    out = []
    # Read base file if present
    if path.exists():
        for line in _read_text_maybe_gz(path).splitlines():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    # Also ingest rotated gz parts, newest last to keep chronological order best-effort
    try:
        for gz in sorted(path.parent.glob(path.name + '.*.jsonl.gz')):
            for line in _read_text_maybe_gz(gz).splitlines():
                try:
                    out.append(json.loads(line))
                except Exception:
                    pass
    except Exception:
        pass
    return out


def nearest_rank(arr: list[float], p: int) -> float:
    if not arr:
        return 0.0
    import math
    n = len(arr)
    rank = max(1, min(n, math.ceil((p / 100.0) * n)))
    return float(sorted(arr)[rank - 1])


def main(window_sec: int = 3600, out_path: str | None = None):
    now = time.time()
    cutoff = now - window_sec

    # Logs
    events = load_jsonl(ROOT / 'logs' / 'aurora_events.jsonl')
    orders_s = load_jsonl(ROOT / 'logs' / 'orders_success.jsonl')
    orders_f = load_jsonl(ROOT / 'logs' / 'orders_failed.jsonl')
    orders_d = load_jsonl(ROOT / 'logs' / 'orders_denied.jsonl')

    def _ts_ok(obj: dict[str, Any]) -> bool:
        # For events: prefer ts_ns as nanoseconds; for orders_* prefer ts_ns/ts_ms; include if no timestamp provided.
        if 'ts_ns' in obj and obj.get('ts_ns') is not None:
            try:
                return (float(obj['ts_ns']) / 1e9) >= cutoff
            except Exception:
                return True
        if 'ts_ms' in obj and obj.get('ts_ms') is not None:
            try:
                return (float(obj['ts_ms']) / 1e3) >= cutoff
            except Exception:
                return True
        ts = obj.get('ts')
        if ts is None:
            return True
        try:
            f = float(ts)
        except Exception:
            return True
        # Heuristic: if ts looks like ms epoch (>= 1e12), convert; else treat as seconds
        tsec = (f / 1e3) if f >= 1e12 else f
        return tsec >= cutoff

    events = [e for e in events if _ts_ok(e)]
    orders_s = [o for o in orders_s if _ts_ok(o)]
    orders_f = [o for o in orders_f if _ts_ok(o)]
    orders_d = [o for o in orders_d if _ts_ok(o)]

    # Orders aggregates
    total = len(orders_s) + len(orders_f) + len(orders_d)
    orders_block = {
        "total": total,
        "success_pct": (len(orders_s) / total) if total else 0.0,
        "rejected_pct": (len(orders_f) / total) if total else 0.0,
        "denied_pct": (len(orders_d) / total) if total else 0.0,
    }

    # Reasons top5 from failed+denied (reason_code)
    reasons = []
    for r in orders_f:
        rc = r.get('reason_code') or r.get('error_code') or 'UNKNOWN'
        reasons.append(rc)
    for r in orders_d:
        rc = r.get('reason_code') or r.get('deny_reason') or 'UNKNOWN'
        reasons.append(rc)
    top5 = Counter(reasons).most_common(5)
    # Also build deny_by_reason shares for report compatibility
    deny_total = len(orders_d)
    deny_counter = Counter([
        (r.get('reason_normalized') or r.get('reason_code') or r.get('deny_reason') or 'UNKNOWN')
        for r in orders_d
    ])
    deny_by_reason = []
    if deny_total > 0:
        for reason, cnt in deny_counter.most_common(5):
            deny_by_reason.append({"reason": reason, "share": cnt / deny_total})

    # Latency from lifecycle events using correlator
    corr = LifecycleCorrelator(window_s=window_sec)
    for ev in events:
        # Map aurora_events schema to correlator inputs
        corr.add_event({
            'cid': ev.get('cid'),
            'oid': ev.get('oid'),
            'ts_ns': ev.get('ts_ns'),
            'type': ev.get('event_code'),
            'qty': (ev.get('details') or {}).get('fill_qty'),
            'fill_qty': (ev.get('details') or {}).get('fill_qty'),
        })
    lat = corr.finalize()

    # Market snapshot averages from orders_* logs
    def _avg(key: str):
        vals = []
        for rr in (orders_s + orders_f + orders_d):
            v = rr.get(key)
            if v is None:
                v = (rr.get('context') or {}).get(key)
            try:
                if v is not None:
                    vals.append(float(v))
            except Exception:
                pass
        return (sum(vals) / len(vals)) if vals else 0.0

    market_snapshot = {
        'spread_bps_avg': _avg('spread_bps'),
        'vol_std_bps_avg': _avg('vol_std_bps'),
    }

    # Gates counts from deny reasons
    gates = {
        'SPREAD_GUARD': 0,
        'VOL_GUARD': 0,
        'LATENCY_GUARD': 0,
        'CVAR_GUARD': 0,
        'DD_GUARD': 0,
        'POSITION_CAP_GUARD': 0,
    }
    for r in orders_d:
        rc = (r.get('reason_code') or '').upper()
        for k in list(gates.keys()):
            if k in rc:
                gates[k] += 1

    # Rewards counts from events
    rewards = {
        'TP': 0,
        'TRAIL': 0,
        'BREAKEVEN': 0,
        'TIME_EXIT': 0,
        'MAX_R_EXIT': 0,
    }
    for ev in events:
        ec = str(ev.get('event_code') or '').upper()
        if ec == 'REWARD.TP':
            rewards['TP'] += 1
        elif ec == 'REWARD.TRAIL':
            rewards['TRAIL'] += 1
        elif ec == 'REWARD.BREAKEVEN':
            rewards['BREAKEVEN'] += 1
        elif ec == 'REWARD.TIMEOUT':
            rewards['TIME_EXIT'] += 1
        elif ec == 'REWARD.MAX_R':
            rewards['MAX_R_EXIT'] += 1

    # Sanity
    records = len(events) + len(orders_s) + len(orders_f) + len(orders_d)
    empty_fields = 0
    unknown_exchange = 0
    for rr in (orders_f + orders_d):
        if not rr.get('reason_code') and not rr.get('reason_detail'):
            empty_fields += 1
        if str(rr.get('reason_code') or '').upper().startswith('EXCHANGE_UNKNOWN'):
            unknown_exchange += 1
    sanity = {
        'records': records,
        'empty_fields_pct': (empty_fields / (len(orders_f) + len(orders_d))) if (orders_f or orders_d) else 0.0,
        'exchange_unknown_pct': (unknown_exchange / (len(orders_f) + len(orders_d))) if (orders_f or orders_d) else 0.0,
    }
    if records == 0:
        sanity['note'] = 'insufficient_data'

    # Extra metrics block expected by tests: slippage percentiles and winrate proxy
    slip_vals = []
    for rr in orders_s:
        v = rr.get('slippage_bps')
        if v is None:
            v = (rr.get('context') or {}).get('slippage_bps')
        try:
            if v is not None:
                slip_vals.append(float(v))
        except Exception:
            pass
    metrics_block = {
        'slippage_p50': nearest_rank(slip_vals, 50),
        'slippage_p95': nearest_rank(slip_vals, 95),
        # winrate proxy: successes / (successes + failures)
        'winrate_proxy': (len(orders_s) / max(1, (len(orders_s) + len(orders_f))))
    }

    summary = {
        'window_sec': window_sec,
        'orders': orders_block,
        'reasons_top5': top5,
        'latency_ms': lat.get('latency_ms', {  # type: ignore[assignment]
            'submit_ack': {'p50': 0.0, 'p95': 0.0, 'p99': 0.0},
            'ack_done': {'p50': 0.0, 'p95': 0.0, 'p99': 0.0},
        }),
        'market_snapshot': market_snapshot,
        'gates': gates,
        'rewards': rewards,
        'sanity': sanity,
        'metrics': metrics_block,
    }
    if deny_by_reason:
        summary['deny_by_reason'] = deny_by_reason

    out = ROOT / 'reports' / 'summary_gate_status.json' if out_path is None else Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary))

    # Write a small run digest markdown for human quick view
    try:
        digest = ROOT / 'reports' / 'run_digest.md'
        lines = [
            f"# Run Digest (last {window_sec}s)",
            "",
            f"Total orders: {orders_block['total']} | Success%: {orders_block['success_pct']:.2f}",
            f"Winrate proxy: {metrics_block['winrate_proxy']:.3f}",
            f"Slippage p50/p95: {metrics_block['slippage_p50']:.2f}/{metrics_block['slippage_p95']:.2f} bps",
        ]
        if deny_by_reason:
            lines.append("")
            lines.append("Top deny reasons:")
            for item in deny_by_reason[:3]:
                lines.append(f"- {item['reason']}: {item['share']*100:.1f}%")
        digest.write_text("\n".join(lines), encoding='utf-8')
    except Exception:
        pass


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--window-sec', type=int, default=3600)
    p.add_argument('--out', type=str, default=str(ROOT / 'reports' / 'summary_gate_status.json'))
    args = p.parse_args()
    main(window_sec=args.window_sec, out_path=args.out)
