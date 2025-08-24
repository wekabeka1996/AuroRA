from __future__ import annotations

from fastapi.testclient import TestClient

# Импортируем приложение и отключаем события старта/остановки, чтобы не инициализировать тяжёлые компоненты
from api.service import app


def _client():
    # Уберём запуск TradingSystem на старте тестов
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    return TestClient(app)


def test_expected_return_allows_when_positive():
    client = _client()
    payload = {
        "account": {"mode": "shadow"},
        "order": {"qty": 1.0},
        "market": {
            # Параметры для гейтов
            "latency_ms": 10.0,
            "slip_bps_est": 1.0,
            # A/B и score для E[Π]
            "a_bps": 5.0,
            "b_bps": 12.0,
            "score": 0.9,
            "mode_regime": "normal",
            "spread_bps": 5.0,
        },
        "fees_bps": 0.5,
    }
    r = client.post("/pretrade/check", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["allow"] is True, data
    assert data["reason"] == "ok"
    assert data["observability"]["reasons"] == []


def test_expected_return_blocks_when_negative():
    client = _client()
    payload = {
        "account": {"mode": "shadow"},
        "order": {"qty": 1.0},
        "market": {
            "latency_ms": 10.0,
            "slip_bps_est": 1.0,
            "a_bps": 10.0,
            "b_bps": 8.0,
            "score": -0.3,
            "mode_regime": "normal",
            "spread_bps": 5.0,
        },
        "fees_bps": 1.0,
    }
    r = client.post("/pretrade/check", json=payload)
    assert r.status_code == 200
    data = r.json()
    assert data["allow"] is False, data
    assert data["reason"] == "expected_return_gate"
    assert any(
        "expected_return_below_threshold" in reason for reason in data["observability"]["reasons"]
    )
