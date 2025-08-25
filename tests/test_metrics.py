import json
import time
from pathlib import Path

import pytest


def test_metrics_aggregates(tmp_path: Path, monkeypatch):
    logs = Path('logs')
    logs.mkdir(exist_ok=True)
    events = logs / 'events.jsonl'
    now_ms = int(time.time() * 1000)
    # write a couple of events
    events.write_text(
        "\n".join([
            json.dumps({"type": "POLICY.DECISION", "code": "AURORA.EXPECTED_RETURN_ACCEPT", "payload": {"ts": now_ms}}),
            json.dumps({"type": "AURORA.RISK_WARN", "code": "HEALTH.LATENCY_P95_HIGH", "payload": {"ts": now_ms}}),
        ]),
        encoding='utf-8'
    )
    from tools.auroractl import metrics
    with pytest.raises(SystemExit) as ei:
        metrics(window_sec=3600)
    # result ATTn -> non-zero
    assert ei.value.code == 1
    assert (Path('reports') / 'summary_gate_status.json').exists()
