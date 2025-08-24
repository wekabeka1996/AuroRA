import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from api.service import app


@contextmanager
def envvar(key: str, value: str):
    old = os.environ.get(key)
    os.environ[key] = value
    try:
        yield
    finally:
        if old is None:
            del os.environ[key]
        else:
            os.environ[key] = old


def _payload_with_trap(cancel=10.0, add=2.0, trades=10):
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001},
        "market": {
            "latency_ms": 5,
            "slip_bps_est": 1.0,
            "a_bps": 8.0,
            "b_bps": 20.0,
            "score": 0.8,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            "trap_cancel_deltas": [cancel] * 5,
            "trap_add_deltas": [add] * 5,
            "trap_trades_cnt": trades,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_trap_guard_score_blocks_when_enabled():
    with envvar("TRAP_GUARD", "on"):
        with envvar("AURORA_TRAP_THRESHOLD", "0.6"):
            with TestClient(app) as client:
                r = client.post("/pretrade/check", json=_payload_with_trap())
                assert r.status_code == 200
                data = r.json()
                assert data["allow"] is False
                assert data["reason"].startswith("trap_guard")
                obs = data.get("observability", {})
                assert obs.get("trap", {}).get("trap_score") is not None


@pytest.mark.anyio
def test_trap_guard_score_respects_rollback():
    with envvar("TRAP_GUARD", "off"):
        with TestClient(app) as client:
            r = client.post("/pretrade/check", json=_payload_with_trap())
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is True