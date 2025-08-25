import json
import time
from pathlib import Path

import pytest


def test_metrics_p95_csv(tmp_path: Path, monkeypatch):
    logs = Path('logs')
    logs.mkdir(exist_ok=True)
    events = logs / 'events.jsonl'
    now_ms = int(time.time() * 1000)
    # Two points: different p95
    events.write_text(
        "\n".join([
            json.dumps({"type": "HEALTH", "code": "HEALTH.LATENCY_P95_HIGH", "payload": {"ts": now_ms-1000, "latency_p95_ms": 250.0}}),
            json.dumps({"type": "HEALTH", "code": "OK", "payload": {"ts": now_ms, "latency_p95_ms": 120.5}}),
        ]),
        encoding='utf-8'
    )
    from tools.auroractl import metrics
    import typer
    with pytest.raises(typer.Exit) as ei:
        metrics(window_sec=3600)
    # ATTN because we included one LATENCY_P95_HIGH alert
    assert getattr(ei.value, 'exit_code', None) == 1
    csv = (Path('artifacts') / 'latency_p95_timeseries.csv').read_text(encoding='utf-8').strip().splitlines()
    assert csv[0] == 'ts,value'
    assert len(csv) == 3
    # second data point matches 120.5
    assert csv[-1].endswith(',120.5')
