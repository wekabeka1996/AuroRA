from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from api.service import app


@contextmanager
def envvars(values: dict[str, str]):
    old = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def base_payload() -> dict:
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001},
        "market": {
            "latency_ms": 10,
            "slip_bps_est": 1.0,
            "a_bps": 8.0,
            "b_bps": 20.0,
            "score": 0.5,
            "mode_regime": "normal",
            "spread_bps": 5.0,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_ops_cooloff_and_reset_and_arm_disarm():
    with envvars({
        "AURORA_LMAX_MS": "1000",
        "AURORA_LATENCY_GUARD_MS": "30",
        "AURORA_LATENCY_WINDOW_SEC": "5",
        "AURORA_COOLOFF_SEC": "2",
    }):
        with TestClient(app) as client:
            # Healthy request allowed
            r1 = client.post("/pretrade/check", json=base_payload())
            assert r1.status_code == 200 and r1.json()["allow"] is True

            # Manual cooloff blocks
            r = client.post("/ops/cooloff/3")
            assert r.status_code == 200
            r2 = client.post("/pretrade/check", json=base_payload())
            assert r2.status_code == 200 and r2.json()["allow"] is False and r2.json()["reason"] == "latency_cooloff"

            # Reset clears cooloff
            r = client.post("/ops/reset")
            assert r.status_code == 200
            r3 = client.post("/pretrade/check", json=base_payload())
            assert r3.status_code == 200 and r3.json()["allow"] is True

            # Disarm blocks with disarmed reason (fail-closed)
            r = client.post("/aurora/disarm")
            assert r.status_code == 200
            r4 = client.post("/pretrade/check", json=base_payload())
            assert r4.status_code == 200 and r4.json()["allow"] is False and r4.json()["reason"] == "latency_disarmed"
            # Arm restores
            r = client.post("/aurora/arm")
            assert r.status_code == 200
            r5 = client.post("/pretrade/check", json=base_payload())
            assert r5.status_code == 200 and r5.json()["allow"] is True
