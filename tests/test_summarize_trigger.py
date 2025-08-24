import json
from pathlib import Path
import importlib


def test_summarize_trigger(tmp_path: Path):
    # Prepare fake logs directory under living_latent/logs
    root = tmp_path / 'living_latent'
    logs = root / 'logs'
    logs.mkdir(parents=True)
    trigger_ts = 1_700_000_000.0
    # blackbox events
    bb = [
        {"event": "run_meta", "run_id": "r123", "config_hash": "abc"},
        {"event": "text_trigger_read", "ts": trigger_ts},
    ]
    (logs / 'blackbox.jsonl').write_text("\n".join(json.dumps(x) for x in bb), encoding='utf-8')
    # kpi entries (surprisal before and after, latency)
    kpi = []
    for dt in (-3000, -10, 10, 3000):
        kpi.append({"ts": trigger_ts + dt, "surprisal": 5 + dt/3000, "latency_ms": 50 + (dt % 7)})
    (logs / 'kpi.jsonl').write_text("\n".join(json.dumps(x) for x in kpi), encoding='utf-8')
    # copy script file from real path
    # Instead of copying we import via relative; create script file referencing our test root.
    mod = importlib.import_module('living_latent.scripts.summarize_run')
    # Monkeypatch ROOT related globals
    setattr(mod, 'ROOT', root)  # type: ignore[attr-defined]
    setattr(mod, 'LOGS', root / 'logs')  # type: ignore[attr-defined]
    setattr(mod, 'BB', (root / 'logs' / 'blackbox.jsonl'))  # type: ignore[attr-defined]
    setattr(mod, 'KPI', (root / 'logs' / 'kpi.jsonl'))  # type: ignore[attr-defined]
    setattr(mod, 'ACC', (root / 'logs' / 'acceptance.json'))  # type: ignore[attr-defined]
    mod.main()
    acc_path = root / 'logs' / 'acceptance.json'
    assert acc_path.exists(), 'acceptance.json not created'
    data = json.loads(acc_path.read_text(encoding='utf-8'))
    assert data['trigger_event_seen'] is True
    assert data['delta_surprisal_calc_method'] == 'text_trigger_read'
    assert data['run_id'] == 'r123'
    assert data['config_hash'] == 'abc'
    assert 'surprisal_p95_pre' in data and 'surprisal_p95_post' in data
    assert 'latency_p95_ms' in data
