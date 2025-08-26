from __future__ import annotations

import json
from pathlib import Path

from tools.metrics_summary import main as metrics_main
import time


def write_jsonl(p: Path, rows):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_metrics_summary_schema_and_values(tmp_path: Path, monkeypatch):
    # Monkeypatch ROOT in module
    from importlib import reload
    import tools.metrics_summary as ms
    reload(ms)
    ms.ROOT = tmp_path
    logs = tmp_path / 'logs'

    # Build synthetic logs
    # Orders success with market context
    write_jsonl(logs / 'orders_success.jsonl', [
        {"context": {"slippage_bps": 2.0}, "spread_bps": 50.0, "vol_std_bps": 120.0},
        {"context": {"slippage_bps": 4.0}, "spread_bps": 60.0, "vol_std_bps": 100.0},
    ])
    # Fail and denied with reason_code
    write_jsonl(logs / 'orders_failed.jsonl', [
        {"reason_code": "EXCHANGE_FILTER_PRICE"},
        {"reason_code": "EXCHANGE_FILTER_PRICE"},
        {"reason_code": "EXCHANGE_FILTER_LOT"},
    ])
    write_jsonl(logs / 'orders_denied.jsonl', [
        {"reason_code": "SPREAD_GUARD"},
        {"reason_code": "LATENCY_GUARD"},
        {"reason_code": "SPREAD_GUARD"},
    ])
    # Lifecycle events for latency
    base = time.time_ns()
    write_jsonl(logs / 'aurora_events.jsonl', [
        {"event_code": "ORDER.SUBMIT", "cid": "A", "ts_ns": base},
        {"event_code": "ORDER.ACK",    "cid": "A", "ts_ns": base + 100_000_000},  # 100ms
        {"event_code": "ORDER.FILL",   "cid": "A", "ts_ns": base + 300_000_000},  # +200ms
        {"event_code": "REWARD.TP", "ts_ns": base + 1_000_000_000},
        {"event_code": "REWARD.TRAIL", "ts_ns": base + 1_100_000_000},
    ])

    ms.main(window_sec=3600, out_path=str(tmp_path / 'reports' / 'summary_gate_status.json'))
    data = json.loads((tmp_path / 'reports' / 'summary_gate_status.json').read_text(encoding='utf-8'))

    # Keys exist
    for k in ("orders", "reasons_top5", "latency_ms", "market_snapshot", "gates", "rewards", "sanity"):
        assert k in data

    # Orders block percentages
    orders = data['orders']
    assert orders['total'] == 8  # 2 success + 3 failed + 3 denied
    assert abs(orders['success_pct'] - (2/8)) < 1e-6
    assert abs(orders['rejected_pct'] - (3/8)) < 1e-6
    assert abs(orders['denied_pct'] - (3/8)) < 1e-6

    # reasons top5 ordering
    top = dict(data['reasons_top5'])
    assert top.get('EXCHANGE_FILTER_PRICE') == 2

    # latency percentiles
    lat = data['latency_ms']
    assert lat['submit_ack']['p50'] in (100.0,)
    assert lat['ack_done']['p50'] in (200.0,)

    # market snapshot averages
    msnap = data['market_snapshot']
    assert msnap['spread_bps_avg'] > 0
    assert msnap['vol_std_bps_avg'] > 0

    # gates and rewards counts
    gates = data['gates']
    assert gates['SPREAD_GUARD'] == 2
    assert gates['LATENCY_GUARD'] == 1
    rewards = data['rewards']
    assert rewards['TP'] == 1 and rewards['TRAIL'] == 1


def test_metrics_summary_empty_data(tmp_path: Path, monkeypatch):
    from importlib import reload
    import tools.metrics_summary as ms
    reload(ms)
    ms.ROOT = tmp_path
    ms.main(window_sec=3600, out_path=str(tmp_path / 'reports' / 'summary_gate_status.json'))
    data = json.loads((tmp_path / 'reports' / 'summary_gate_status.json').read_text(encoding='utf-8'))
    assert data['sanity']['records'] == 0
    assert data['sanity'].get('note') == 'insufficient_data'
