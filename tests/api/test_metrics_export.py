import os
import importlib
from fastapi.testclient import TestClient


def make_client(tmp_path) -> TestClient:
    os.environ['AURORA_API_TOKEN'] = 'z' * 36
    os.environ['AURORA_IP_ALLOWLIST'] = '127.0.0.1'
    import os as _os
    _os.chdir(tmp_path)
    import api.service as svc
    importlib.reload(svc)
    return TestClient(svc.app)


def test_metrics_contains_sli_series(tmp_path):
    client = make_client(tmp_path)
    r = client.get('/metrics')
    assert r.status_code == 200
    txt = r.text
    # core and SLI metrics
    for name in [
        'aurora_prediction_requests_total',
        'aurora_deny_rate_15m',
        'aurora_latency_p99_ms',
        'aurora_ece',
        'aurora_cvar95_min',
        'aurora_sse_clients',
    ]:
        assert name in txt, f"missing {name} in metrics output"
# -*- coding: utf-8 -*-
import os
from fastapi.testclient import TestClient

os.environ.setdefault('AURORA_MODE', 'live')
os.environ.setdefault('AURORA_API_TOKEN', 'local_dev_secret_1234567890')

from api.service import app  # noqa: E402

client = TestClient(app)


def test_metrics_presence():
    r = client.get('/metrics')
    assert r.status_code == 200
    text = r.text
    # Check presence of new SLI names
    for name in [
        'aurora_deny_rate_15m',
        'aurora_latency_p99_ms',
        'aurora_ece',
        'aurora_cvar95_min',
        'aurora_sse_clients',
        'aurora_sse_disconnects_total',
        'aurora_parent_gate_allow_total',
        'aurora_parent_gate_deny_total',
        'aurora_expected_net_reward_blocked_total',
        'aurora_orders_submitted_shadow_total',
        'aurora_orders_denied_total',
    ]:
        assert name in text, name
