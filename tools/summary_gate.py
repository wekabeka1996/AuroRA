from __future__ import annotations

import argparse
import json
import re
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Ensure project root on sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from observability.codes import RISK_DENY, is_latency


def load_summary_md(path: Path) -> dict:
    text = path.read_text(encoding='utf-8') if path.exists() else ''
    data = {
        'reasons': {},
        'risk': {},
        'slippage': {'mae': 'N/A', 'ratio': 'N/A'},
    'latency': {'p95_ms': 'N/A'},
    }
    # Parse Reasons table rows: | code | count | percent |
    for line in text.splitlines():
        line = line.strip()
        if line.startswith('|') and 'percent' not in line.lower() and 'code' not in line.lower():
            cells = [c.strip() for c in line.strip('|').split('|')]
            if len(cells) >= 2:
                code = cells[0]
                try:
                    count = int(cells[1])
                except Exception:
                    continue
                data['reasons'][code] = count
        if line.startswith('MAE (bps):'):
            try:
                data['slippage']['mae'] = float(line.split(':',1)[1].strip())
            except Exception:
                pass
        if line.startswith('slip_mae_ratio:'):
            try:
                data['slippage']['ratio'] = float(line.split(':',1)[1].strip())
            except Exception:
                pass
        if line.startswith('latency_p95_ms:'):
            try:
                data['latency']['p95_ms'] = float(line.split(':',1)[1].strip())
            except Exception:
                pass
    return data


essential_codes = {
    'expected_return_gate',
    'slippage_guard',
}


def parse_events(path: Path):
    if not path.exists():
        return []
    out = []
    for s in path.read_text(encoding='utf-8').splitlines():
        s = s.strip()
        if not s:
            continue
        try:
            out.append(json.loads(s))
        except Exception:
            continue
    return out


def count_expected_return_accepts(events) -> int:
    cnt = 0
    for ev in events[-5000:]:
        t = str(ev.get('type') or '')
        code = str(ev.get('code') or '')
        payload = ev.get('payload') or {}
        if code == 'AURORA.EXPECTED_RETURN_ACCEPT':
            cnt += 1
            continue
        # Fallback: POLICY.DECISION with reasons contains expected_return_accept
        if t == 'POLICY.DECISION':
            reasons = payload.get('reasons') or []
            if isinstance(reasons, list) and any(r == 'expected_return_accept' for r in reasons):
                cnt += 1
    return cnt


def window_counts(events, predicate, window_sec: int):
    # Use timezone-aware UTC datetimes to avoid naive/aware comparison issues
    now = datetime.now(timezone.utc)
    start = now - timedelta(seconds=window_sec)
    cnt = 0
    buckets = {}
    for ev in events[-2000:]:
        if not predicate(ev):
            continue
        ts = ev.get('ts')
        try:
            tdt = datetime.fromisoformat(ts.replace('Z','+00:00')) if isinstance(ts, str) else now
            # Ensure timezone-aware
            if tdt.tzinfo is None:
                tdt = tdt.replace(tzinfo=timezone.utc)
        except Exception:
            tdt = now
        if tdt < start:
            continue
        key = ev.get('code') or ev.get('type')
        buckets[key] = buckets.get(key, 0) + 1
        cnt += 1
    return cnt, buckets


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--summary', default='reports/canary_60min_summary.md')
    p.add_argument('--events', default='logs/events.jsonl')
    p.add_argument('--strict', action='store_true')
    p.add_argument('--status-out', default=None, help='Optional path to write JSON status {result, violations}.')
    p.add_argument('--slip-threshold', type=float, default=0.30)
    p.add_argument('--risk-threshold', type=int, default=2)
    p.add_argument('--latency-threshold', type=int, default=2)
    p.add_argument('--window-sec', type=int, default=300)
    p.add_argument('--time-window-last', type=int, default=None, help='Alias for --window-sec; overrides if provided.')
    args = p.parse_args()

    # Optional rollback lever: allow skipping via env
    # Disable SKIP in CI or protected branches
    ci = str(os.getenv('CI', 'false')).lower() == 'true'
    ref = os.getenv('GITHUB_REF') or os.getenv('GITHUB_REF_NAME') or os.getenv('GIT_BRANCH', '')
    ref = str(ref)
    protected = ref.startswith('refs/heads/main') or ref.startswith('main') or ref.startswith('refs/heads/release/') or ref.startswith('release/')
    if not (ci or protected):
        if str(os.getenv('SUMMARY_GATE_SKIP', '0')).lower() in {'1', 'true', 'yes'}:
            print('SUMMARY GATE: SKIPPED by env SUMMARY_GATE_SKIP')
            return

    summary_path = Path(args.summary)
    events_path = Path(args.events)
    summary = load_summary_md(summary_path)
    events = parse_events(events_path)

    violations = []
    # Rule: slip_mae_ratio > threshold
    try:
        ratio = summary['slippage']['ratio']
        if isinstance(ratio, float) and ratio > args.slip_threshold:
            violations.append(f'slippage_ratio>{args.slip_threshold} (got {ratio:.3f})')
    except Exception:
        pass

    # Rule: >=2 same RISK.DENY in window
    def is_risk_deny(ev):
        return str(ev.get('type') or '').upper() == RISK_DENY
    win = int(args.time_window_last) if args.time_window_last is not None else int(args.window_sec)
    _, risk_bucket = window_counts(events, is_risk_deny, win)
    if any(c >= args.risk_threshold for c in risk_bucket.values()):
        top = max(risk_bucket.items(), key=lambda x: x[1])
        violations.append(f'risk_deny_repeated:{top[0]}x{top[1]}')

    # Rule: >=2 HEALTH.LATENCY_* in window
    def is_latency_ev(ev):
        return is_latency(ev.get('type') or ev.get('code') or '')
    lat_cnt, _ = window_counts(events, is_latency_ev, win)
    if lat_cnt >= args.latency_threshold:
        violations.append(f'latency_events>={args.latency_threshold} (got {lat_cnt})')

    # Rule: at least one profitable opportunity over the period
    has_er_accept_signal = False
    # Prefer explicit count from events
    er_cnt = count_expected_return_accepts(events)
    if er_cnt > 0:
        has_er_accept_signal = True
    else:
        # Proxy via reasons table if present (legacy)
        reasons_tab = summary.get('reasons') or {}
        for k, v in reasons_tab.items():
            try:
                cnt = int(v)
            except Exception:
                cnt = 0
            if (k in {"expected_return_gate", "sprt_accept"}) and cnt > 0:
                has_er_accept_signal = True
                break
    if args.strict and not has_er_accept_signal:
        violations.append('NO_VALID_OPPORTUNITIES')

    result = 'OK' if not violations else 'FAIL'

    # Emit optional machine-readable status for CI
    if args.status_out:
        try:
            out = {
                'result': result,
                'violations': violations,
                'summary_path': str(summary_path),
                'events_path': str(events_path),
                'params': {
                    'strict': bool(args.strict),
                    'slip_threshold': float(args.slip_threshold),
                    'risk_threshold': int(args.risk_threshold),
                    'latency_threshold': int(args.latency_threshold),
                    'window_sec': int(args.time_window_last) if args.time_window_last is not None else int(args.window_sec),
                },
                'computed': {
                    'latency_p95_ms': (summary.get('latency') or {}).get('p95_ms'),
                    'slip_ratio': (summary.get('slippage') or {}).get('ratio'),
                    'expected_return_accepts': er_cnt,
                },
                'timestamp': datetime.now(timezone.utc).isoformat().replace('+00:00','Z'),
            }
            Path(args.status_out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.status_out).write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding='utf-8')
        except Exception as e:
            print(f"WARN: failed to write status file to {args.status_out}: {e}")

    # Optional: push Prometheus metrics to a Pushgateway if configured
    # Controlled by env AURORA_PUSHGATEWAY (URL). Labels branch/sha derived from CI env.
    try:
        pgw = os.getenv('AURORA_PUSHGATEWAY') or os.getenv('PUSHGATEWAY_URL')
        if pgw:
            from prometheus_client import CollectorRegistry, Gauge, Counter, push_to_gateway, pushadd_to_gateway
            reg = CollectorRegistry()
            last_status = Gauge('aurora_summary_gate_last_status', 'Last summary gate status: 0=OK,1=FAIL', ['branch', 'sha'], registry=reg)
            last_ts = Gauge('aurora_summary_gate_last_run_ts', 'Last summary gate run timestamp (unix)', registry=reg)
            # For fail counts, we use pushadd to accumulate
            fail_total = Counter('aurora_summary_gate_fail_total', 'Total failed gates by reason', ['reason'])

            branch = os.getenv('GITHUB_REF_NAME') or os.getenv('GITHUB_REF') or os.getenv('BRANCH') or 'unknown'
            sha = os.getenv('GITHUB_SHA') or os.getenv('SHA') or 'unknown'
            last_status.labels(branch=branch, sha=sha).set(0 if result == 'OK' else 1)
            last_ts.set(int(datetime.now(timezone.utc).timestamp()))
            # Push gauges (replace)
            push_to_gateway(pgw, job='summary_gate', registry=reg)
            # Increment fail reasons (add) if failed
            if result != 'OK':
                for reason in violations:
                    try:
                        # Create a tiny registry per add to avoid mixing metrics
                        r2 = CollectorRegistry()
                        c = Counter('aurora_summary_gate_fail_total', 'Total failed gates by reason', ['reason'], registry=r2)
                        c.labels(reason=reason).inc()
                        pushadd_to_gateway(pgw, job='summary_gate', registry=r2)
                    except Exception:
                        pass
    except Exception as e:
        print(f"WARN: failed to push metrics: {e}")

    if violations:
        print('SUMMARY GATE: FAIL')
        for v in violations:
            print('-', v)
        raise SystemExit(1)
    print('SUMMARY GATE: OK')


if __name__ == '__main__':
    main()
