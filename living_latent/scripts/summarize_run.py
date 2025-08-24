from __future__ import annotations
"""Summarize run logs into acceptance.json with trigger + meta fields.

Expected layout (adjustable in tests):
  ROOT/logs/blackbox.jsonl  (events: run_meta, text_trigger_read, ...)
  ROOT/logs/kpi.jsonl       (surprisal, latency_ms samples across time)
  ROOT/logs/acceptance.json (output written/merged)

We compute delta surprisal around text_trigger_read event if present.
"""
import json, math, statistics, hashlib
from pathlib import Path
from typing import Dict, Any, List

ROOT = Path('living_latent')
LOGS = ROOT / 'logs'
BB = LOGS / 'blackbox.jsonl'
KPI = LOGS / 'kpi.jsonl'
ACC = LOGS / 'acceptance.json'

PRE_WINDOW_S = 3600.0  # 1h before trigger for baseline
POST_WINDOW_S = 3600.0 # 1h after


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open('r', encoding='utf-8') as f:
        for line in f:
            line=line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows

def quantile_p95(values: List[float]) -> float:
    if not values:
        return float('nan')
    arr = sorted(values)
    k = int(0.95*(len(arr)-1))
    return float(arr[k])

def main():
    bb_rows = load_jsonl(BB)
    kpi_rows = load_jsonl(KPI)
    run_id = None
    config_hash = None
    trigger_ts = None
    for r in bb_rows:
        ev = r.get('event')
        if ev == 'run_meta':
            run_id = r.get('run_id')
            config_hash = r.get('config_hash')
        elif ev == 'text_trigger_read':
            trigger_ts = r.get('ts')
    # KPI extraction
    surp_series = [(r.get('ts'), r.get('surprisal')) for r in kpi_rows if r.get('surprisal') is not None]
    lat_series = [(r.get('ts'), r.get('latency_ms')) for r in kpi_rows if r.get('latency_ms') is not None]
    def _window(series, center, before, after):
        # Returns list of values (not (t,v) pairs) inside the window.
        return [v for t, v in series if center - before <= t <= center + after]
    if trigger_ts is not None:
        pre_surp_vals = _window(surp_series, trigger_ts, PRE_WINDOW_S, 0.0)
        post_surp_vals = _window(surp_series, trigger_ts, 0.0, POST_WINDOW_S)
        surp_p95_pre = quantile_p95([v for v in pre_surp_vals if isinstance(v, (int, float))])
        surp_p95_post = quantile_p95([v for v in post_surp_vals if isinstance(v, (int, float))])
    else:
        surp_p95_pre = quantile_p95([v for _, v in surp_series if isinstance(v, (int, float))])
        surp_p95_post = surp_p95_pre
    lat_p95 = quantile_p95([v for _, v in lat_series if isinstance(v, (int, float))])
    acc_prev: Dict[str, Any] = {}
    if ACC.exists():
        try:
            acc_prev = json.loads(ACC.read_text(encoding='utf-8'))
        except Exception:
            acc_prev = {}
    acc_prev.update({
        'trigger_event_seen': trigger_ts is not None,
        'delta_surprisal_calc_method': 'text_trigger_read' if trigger_ts is not None else 'global',
        'surprisal_p95_pre': surp_p95_pre,
        'surprisal_p95_post': surp_p95_post,
        'latency_p95_ms': lat_p95,
    })
    if acc_prev.get('run_id') is None and run_id is not None:
        acc_prev['run_id'] = run_id
    if acc_prev.get('config_hash') is None and config_hash is not None:
        acc_prev['config_hash'] = config_hash
    ACC.parent.mkdir(parents=True, exist_ok=True)
    ACC.write_text(json.dumps(acc_prev, indent=2), encoding='utf-8')
    print(json.dumps({'acceptance_summary_written': str(ACC)}, indent=2))

if __name__ == '__main__':  # pragma: no cover
    main()
