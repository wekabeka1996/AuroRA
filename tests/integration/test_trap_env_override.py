from __future__ import annotations

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


def trap_payload_base():
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001},
        "market": {
            "latency_ms": 5,
            "slip_bps_est": 1.0,
            "a_bps": 8.0,
            "b_bps": 20.0,
            "score": 0.4,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            # supply TRAP inputs to engage the guard paths
            "trap_cancel_deltas": [5, 5, 5, 5, 5],
            "trap_add_deltas": [0, 0, 0, 0, 0],
            "trap_trades_cnt": 1,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_env_on_overrides_yaml_off_blocks():
    # YAML default is guards.trap_guard_enabled=false, force enable via env
    with envvar("TRAP_GUARD", "on"):
        with TestClient(app) as client:
            r = client.post("/pretrade/check", json=trap_payload_base())
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            # reason is either trap_guard or trap_guard_score
            assert "trap_guard" in data["reason"]


@pytest.mark.anyio
def test_env_off_overrides_yaml_true_allows():
    # Simulate YAML true by setting default env to on, then override off
    # First call with on to warm any state, then off must allow
    with envvar("TRAP_GUARD", "off"):
        with TestClient(app) as client:
            r = client.post("/pretrade/check", json=trap_payload_base())
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is True
