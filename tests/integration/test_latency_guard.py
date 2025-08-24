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


def base_payload(latency_ms: float) -> dict:
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001},
        "market": {
            "latency_ms": latency_ms,
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
def test_latency_escalations_warn_cooloff_halt():
    # Make immediate guard permissive to exercise p95 logic; small window for quick aggregation
    with envvars({
        "AURORA_LMAX_MS": "1000",
        "AURORA_LATENCY_GUARD_MS": "30",
        "AURORA_LATENCY_WINDOW_SEC": "1",
        "AURORA_COOLOFF_SEC": "2",
        "AURORA_HALT_THRESHOLD_REPEATS": "2",
    }):
        with TestClient(app) as client:
            # Warm samples under threshold
            for _ in range(3):
                r = client.post("/pretrade/check", json=base_payload(5))
                assert r.status_code == 200 and r.json()["allow"] is True
            # Spike latency to trigger WARN and cooloff
            r = client.post("/pretrade/check", json=base_payload(200))
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "latency_cooloff"
            # Next spike during cooloff escalates to HALT
            r2 = client.post("/pretrade/check", json=base_payload(200))
            data2 = r2.json()
            assert data2["allow"] is False
            assert data2["reason"] == "latency_halt"
