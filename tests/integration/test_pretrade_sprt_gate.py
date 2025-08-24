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


def _base_payload():
    # Shape must match PretradeCheckRequest: account/order/market dicts
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001},
        "market": {
            "latency_ms": 5,
            "slip_bps_est": 1.5,
            "a_bps": 8.0,
            "b_bps": 20.0,
            "score": 0.8,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            # Provide samples so SPRT branch runs
            "sprt_samples": [0.5] * 50,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_sprt_enabled_blocks_or_continues():
    with envvar("AURORA_SPRT_ENABLED", "1"):
        with TestClient(app) as client:
            payload = _base_payload()
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert "allow" in data
            # Ensure SPRT observability is present when enabled
            obs = data.get("observability", {})
            sprt_obs = obs.get("sprt", {})
            assert "decision" in sprt_obs
            # With samples provided and enabled, decision should not be None
            assert sprt_obs.get("decision") is not None


@pytest.mark.anyio
def test_sprt_rollback_disables_gate():
    with envvar("AURORA_SPRT_ENABLED", "0"):
        with TestClient(app) as client:
            payload = _base_payload()
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            obs = data.get("observability", {})
            sprt_obs = obs.get("sprt", {})
            # When disabled, decision should be None
            assert sprt_obs.get("decision") is None
