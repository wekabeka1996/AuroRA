from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from api.service import app


def test_pretrade_contract_valid_minimal():
    client = TestClient(app)
    payload = {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 1.0, "base_notional": 100.0},
        "market": {"latency_ms": 1.0, "a_bps": 10.0, "b_bps": 20.0, "score": 0.1, "spread_bps": 5.0},
    }
    r = client.post("/pretrade/check", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data["allow"], bool)
    assert isinstance(data["max_qty"], (int, float))
    assert "observability" in data
    # Optional sections can be missing but must not break
    assert "risk_scale" in data


def test_pretrade_contract_invalid_type_422():
    client = TestClient(app)
    payload = {
        "account": "not-a-dict",  # invalid
        "order": {},
        "market": {},
    }
    r = client.post("/pretrade/check", json=payload)
    assert r.status_code in (400, 422)


def test_response_optional_sections():
    client = TestClient(app)
    payload = {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 1.0, "base_notional": 100.0},
        "market": {"latency_ms": 1.0, "a_bps": 10.0, "b_bps": 20.0, "score": 0.1, "spread_bps": 5.0},
    }
    r = client.post("/pretrade/check", json=payload)
    data = r.json()
    # observability may contain trap/sprt/risk or not; should be dict
    assert isinstance(data.get("observability"), dict)
