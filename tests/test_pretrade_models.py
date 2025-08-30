from __future__ import annotations

import importlib
from fastapi.testclient import TestClient


def test_pretrade_allows_minimal_payload():
    svc = importlib.import_module("api.service")
    app = svc.app
    client = TestClient(app)

    body = {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "LONG", "qty": 0.01, "price": 100.0},
        "market": {"latency_ms": 1.0, "score": 0.0, "a_bps": 10.0, "b_bps": 10.0, "spread_bps": 2.0},
        "fees_bps": 1.0,
    }
    r = client.post("/pretrade/check", json=body)
    assert r.status_code == 200
    data = r.json()
    assert set(["allow", "max_qty", "risk_scale", "cooldown_ms", "reason", "hard_gate", "quotas", "observability"]) <= set(data.keys())
    assert isinstance(data["observability"], dict)


def test_pretrade_blocks_on_large_spread():
    svc = importlib.import_module("api.service")
    app = svc.app
    client = TestClient(app)

    body = {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "LONG", "qty": 0.01, "price": 100.0},
        "market": {"latency_ms": 1.0, "score": 0.0, "a_bps": 10.0, "b_bps": 10.0, "spread_bps": 1000.0},
        "fees_bps": 1.0,
    }
    r = client.post("/pretrade/check", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["allow"] is False
    # reason либо содержит spread_bps_too_wide, либо присутствует соответствующая причина в списке reasons
    obs = data.get("observability", {})
    reasons = obs.get("reasons", [])
    assert (isinstance(data.get("reason"), str) and "spread" in data.get("reason")) or any("spread" in str(x) for x in reasons)
