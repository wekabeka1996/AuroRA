from __future__ import annotations

import argparse
import json
import sys
from collections import deque, Counter
from datetime import datetime, timedelta
from pathlib import Path

import time
import requests


def parse_events(path: Path):
    if not path.exists():
        return []
    out = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except Exception:
                continue
    return out


def risk_should_fail(events: list[dict], window_sec: int, threshold: int) -> tuple[bool, str]:
    # track RISK.DENY reasons in a moving window
    now = datetime.utcnow()
    window_start = now - timedelta(seconds=window_sec)
    reasons = []
    for ev in events[-1000:]:
        t = str(ev.get('type') or '')
        if t != 'RISK.DENY':
            continue
        ts = ev.get('ts')
        try:
            tdt = datetime.fromisoformat(ts.replace('Z','+00:00')) if isinstance(ts, str) else now
        except Exception:
            tdt = now
        if tdt < window_start:
            continue
        payload = ev.get('payload') or {}
        reason = (payload.get('reason') or ev.get('code') or 'RISK.DENY').strip()
        reasons.append(reason)
    if not reasons:
        return False, ''
    cnt = Counter(reasons)
    top_reason, top_count = cnt.most_common(1)[0]
    return (top_count >= threshold), top_reason


def get_risk_snapshot(base_url: str, token: str) -> dict:
    headers = {'X-OPS-TOKEN': token}
    r = requests.get(f'{base_url}/risk/snapshot', headers=headers, timeout=5)
    r.raise_for_status()
    return r.json()


def call_cooloff(base_url: str, token: str, sec: int) -> bool:
    try:
        headers = {'X-OPS-TOKEN': token}
        r = requests.post(f'{base_url}/ops/cooloff/{sec}', headers=headers, timeout=5)
        return r.status_code in (200, 201)
    except Exception:
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--events', default='logs/events.jsonl')
    p.add_argument('--base-url', default='http://127.0.0.1:8000')
    p.add_argument('--ops-token', default=None)
    p.add_argument('--window-sec', type=int, default=300)
    p.add_argument('--risk-threshold', type=int, default=2)
    p.add_argument('--no-risk-fail', action='store_true')
    p.add_argument('--no-autocooloff', action='store_true')
    p.add_argument('--cooloff-sec', type=int, default=120)
    # Compatibility flag: accepted but not used here (duration is controlled by the caller)
    p.add_argument('--duration-min', type=int, default=None, help='Optional duration (minutes); accepted for compatibility, not used')
    args = p.parse_args()

    events = parse_events(Path(args.events))
    if not args.no_risk_fail:
        fail, top_reason = risk_should_fail(events, args.window_sec, args.risk_threshold)
        # pre-emptive cooloff on first breach (if any risk events present but not yet exceeding threshold)
        if not args.no_autocooloff and args.ops_token:
            # if there is at least one RISK.DENY in window but below threshold, try cooloff
            _, buckets = risk_should_fail(events, args.window_sec, 1)
            # risk_should_fail returns tuple(bool, str); reuse window_counts instead
            # Simplify: if we already failed OR we have any risk events, call cooloff once
            has_any = False
            for ev in events[-1000:]:
                if str(ev.get('type') or '') == 'RISK.DENY':
                    has_any = True
                    break
            if has_any and not fail:
                call_cooloff(args.base_url, args.ops_token, args.cooloff_sec)

        if fail:
            snapshot = {}
            if args.ops_token:
                try:
                    snapshot = get_risk_snapshot(args.base_url, args.ops_token)
                except Exception as e:
                    snapshot = {'error': str(e)}
            report = {
                'stop_reason': 'RISK_THROTTLE',
                'top_risk_reason': top_reason,
                'risk_snapshot': snapshot,
            }
            print(json.dumps(report, indent=2))
            # graceful stop hint (caller should send SIGINT to its processes)
            sys.exit(1)

    print('Harness OK: no risk stop triggered')


if __name__ == '__main__':
    main()
