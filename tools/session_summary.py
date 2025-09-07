"""Session summary & markdown rendering utilities (restored minimal version).

Used by runner (run_live_aurora) + integration tests. This reconstruction
is derived from tests expectations in tests/integration/test_observability_summary.py.
"""
from __future__ import annotations

from pathlib import Path
import json
from typing import Any, Dict, List
import statistics

# Helper to read JSONL

def _read_jsonl(path: Path, max_lines: int | None = None) -> List[dict]:
    out: List[dict] = []
    if not path.exists():
        return out
    try:
        with path.open('r', encoding='utf-8') as f:
            for i, line in enumerate(f):
                if max_lines and i >= max_lines:
                    break
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return out
    return out


def summarize_session(session_dir: Path | str, max_lines: int = 200_000) -> Dict[str, Any]:
    session_dir = Path(session_dir)
    events = _read_jsonl(session_dir / 'aurora_events.jsonl', max_lines=max_lines)
    orders_success = _read_jsonl(session_dir / 'orders_success.jsonl', max_lines=max_lines)
    orders_failed = _read_jsonl(session_dir / 'orders_failed.jsonl', max_lines=max_lines)
    orders_denied = _read_jsonl(session_dir / 'orders_denied.jsonl', max_lines=max_lines)

    # Collect symbols & order stats
    symbols = sorted({e.get('details', {}).get('symbol') for e in events if isinstance(e.get('details'), dict) and e.get('details', {}).get('symbol')} | {o.get('symbol') for o in orders_success if o.get('symbol')} | {o.get('symbol') for o in orders_denied if o.get('symbol')})

    def _count_status(lst: List[dict], status: str) -> int:
        return sum(1 for o in lst if o.get('status') == status)

    submitted = len(orders_success)
    ack = _count_status(orders_success, 'ack')
    filled = _count_status(orders_success, 'filled')
    partially = _count_status(orders_success, 'partially_filled')
    cancelled = _count_status(orders_success, 'cancelled')
    denied = len(orders_denied)
    failed = len(orders_failed)

    # Routes counts from events ORDER.ROUTE.*
    routes: Dict[str, int] = {}
    for e in events:
        code = e.get('event_code') or ''
        if code.startswith('ORDER.ROUTE.'):
            route = code.split('.')[-1].lower()
            routes[route] = routes.get(route, 0) + 1

    # Governance metrics
    sprt_updates = sum(1 for e in events if e.get('event_code') == 'GOVERNANCE.SPRT.UPDATE')
    alpha_active = 0
    for e in events:
        if e.get('event_code') == 'GOVERNANCE.SNAPSHOT.OK':
            try:
                alpha_active = max(alpha_active, int(e.get('details', {}).get('active_tests') or 0))
            except Exception:
                pass

    # Latency decision_ms from ORDER.ROUTE.* events
    decision_ms_vals: List[float] = []
    for e in events:
        if (e.get('event_code') or '').startswith('ORDER.ROUTE.'):
            try:
                decision_ms_vals.append(float(e.get('details', {}).get('decision_ms') or 0.0))
            except Exception:
                pass
    def _pct(vals: List[float], p: float) -> float:
        if not vals:
            return 0.0
        s = sorted(vals)
        k = max(0, min(len(s)-1, int(round((p/100.0)*(len(s)-1)))))
        return s[k]

    latency = {
        'decision_ms_p50': _pct(decision_ms_vals, 50),
        'decision_ms_p90': _pct(decision_ms_vals, 90),
        'decision_ms_p99': _pct(decision_ms_vals, 99),
        'decision_ms_samples': len(decision_ms_vals),
    }

    # XAI / why-code counts from events details.why
    why_counts: Dict[str, int] = {}
    for e in events:
        why = e.get('details', {}).get('why')
        if why:
            why_counts[str(why)] = why_counts.get(str(why), 0) + 1

    summary = {
        'session': {
            'symbols': symbols,
            'orders': {
                'submitted': submitted,
                'ack': ack,
                'filled': filled,
                'partially_filled': partially,
                'cancelled': cancelled,
                'denied': denied,
                'failed': failed,
            },
            'routes': routes,
        },
        'governance': {
            'alpha': {'totals': {'active': alpha_active}},
            'sprt': {'updates': sprt_updates},
        },
        'latency': latency,
        'xai': {'why_code_counts': why_counts},
    }
    return summary


def render_markdown(summary: Dict[str, Any]) -> str:
    lines: List[str] = []
    sess = summary.get('session', {})
    lines.append('# Trading Session Summary')
    
    # Orders Overview section
    lines.append('\n## Orders Overview')
    orders = sess.get('orders', {})
    lines.append(f"Submitted | {orders.get('submitted', 0)}")
    lines.append(f"Filled | {orders.get('filled', 0)}")
    lines.append(f"Denied | {orders.get('denied', 0)}")
    
    # Route Distribution section
    lines.append('\n## Route Distribution')
    routes = sess.get('routes', {})
    for route_type, count in routes.items():
        pct = 0.0 if not orders.get('submitted') else (count / orders.get('submitted')) * 100
        lines.append(f"{route_type.title()} | {count} | {pct:.1f}%")
    
    # Governance Alpha section
    lines.append('\n## Governance Alpha')
    gov = summary.get('governance', {})
    alpha = gov.get('alpha', {}).get('totals', {})
    lines.append(f"Active Tests | {alpha.get('active', 0)}")
    lines.append(f"Closed Tests | {alpha.get('closed', 0)}")
    lines.append(f"Allocation | {alpha.get('alloc', 0):.2f}")
    lines.append(f"Spent | {alpha.get('spent', 0):.2f}")
    
    # SPRT Statistics section
    lines.append('\n## SPRT Statistics')
    sprt = gov.get('sprt', {})
    lines.append(f"Updates | {sprt.get('updates', 0)}")
    final = sprt.get('final', {})
    lines.append(f"Accept H0 | {final.get('accept_h0', 0)}")
    lines.append(f"Accept H1 | {final.get('accept_h1', 0)}")
    lines.append(f"Timeout | {final.get('timeout', 0)}")
    
    # Latency Performance section
    lines.append('\n## Latency Performance')
    latency = summary.get('latency', {})
    lines.append(f"Decision P50 | {latency.get('decision_ms_p50', 0)}ms")
    lines.append(f"Decision P90 | {latency.get('decision_ms_p90', 0)}ms")
    lines.append(f"Decision P99 | {latency.get('decision_ms_p99', 0)}ms")
    lines.append(f"To First Fill P50 | {latency.get('to_first_fill_ms_p50', 0)}ms")
    lines.append(f"To First Fill P90 | {latency.get('to_first_fill_ms_p90', 0)}ms")
    
    # SLA section
    lines.append('\n## SLA Performance')
    sla = summary.get('sla', {})
    lines.append(f"Breaches | {sla.get('breaches', 0)}")
    lines.append(f"Guard Denies | {sla.get('guard_denies', 0)}")
    
    # Edge section
    lines.append('\n## Edge Performance')
    edge = summary.get('edge', {})
    lines.append(f"Avg Edge BPS | {edge.get('avg_edge_bps', 0)}")
    lines.append(f"Maker Share % | {edge.get('maker_share_pct', 0)}%")
    lines.append(f"Taker Share % | {edge.get('taker_share_pct', 0)}%")
    
    # Top WHY Codes section
    lines.append('\n## Top WHY Codes')
    xai = summary.get('xai', {})
    why_counts = xai.get('why_code_counts', {})
    if why_counts:
        # Sort by count descending and show top 3
        sorted_whys = sorted(why_counts.items(), key=lambda x: x[1], reverse=True)
        for i, (why_code, count) in enumerate(sorted_whys[:3]):
            lines.append(f"{why_code} | {count} occurrences")
    else:
        lines.append("No WHY codes found")
    
    # Summary section
    lines.append('\n## Summary')
    lines.append(f"Total orders: {orders.get('submitted', 0)}")
    lines.append(f"Session duration: {sess.get('duration_s', 0)}s")
    symbols = sess.get('symbols', [])
    lines.append(f"Symbols traded: {', '.join(symbols) if symbols else 'None'}")
    
    return '\n'.join(lines)

if __name__ == '__main__':  # manual test
    import sys
    sd = Path(sys.argv[1] if len(sys.argv) > 1 else '.')
    print(render_markdown(summarize_session(sd)))
