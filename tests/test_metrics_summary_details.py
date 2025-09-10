from __future__ import annotations

import json
from pathlib import Path


def write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_metrics_summary_enriched(tmp_path: Path, monkeypatch):
    # place logs under project logs path by monkeypatching ROOT
    from importlib import reload
    import tools.metrics_summary as ms
    reload(ms)
    ms.ROOT = tmp_path
    logs = tmp_path / 'logs'
    write_jsonl(logs / 'orders_success.jsonl', [
        {"context": {"slippage_bps": 1.0}},
        {"context": {"slippage_bps": 3.0}},
        {"context": {"slippage_bps": 5.0}},
    ])
    write_jsonl(logs / 'orders_failed.jsonl', [{}, {}])
    write_jsonl(logs / 'orders_denied.jsonl', [
        {"reason_normalized": "PRICE_FILTER"},
        {"reason_normalized": "PRICE_FILTER"},
        {"reason_normalized": "TIMESTAMP"},
    ])
    write_jsonl(logs / 'events.jsonl', [{}])
    # run
    ms.main(window_sec=3600)
    data = json.loads((tmp_path / 'reports' / 'summary_gate_status.json').read_text(encoding='utf-8'))
    assert data['metrics']['slippage_p50'] == 3.0
    assert data['metrics']['slippage_p95'] >= 5.0 - 1e-9
    assert data['metrics']['winrate_proxy'] == 3 / 5
    top = data['deny_by_reason']
    assert top[0]['reason'] == 'PRICE_FILTER' and abs(top[0]['share'] - (2/3)) < 1e-6
    assert (tmp_path / 'reports' / 'run_digest.md').exists()
