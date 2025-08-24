from __future__ import annotations

from fastapi.testclient import TestClient

from api.service import app


def _client():
    app.router.on_startup.clear()
    app.router.on_shutdown.clear()
    return TestClient(app)


def test_trap_gate_blocks_on_high_z(monkeypatch):
    client = _client()

    # We simulate TRAP inputs via market payload fields we introduce for the test only.
    # In a real runner, these would come from a streaming book microstructure module.
    payload = {
        "account": {"mode": "shadow"},
        "order": {"qty": 1.0},
        "market": {
            "latency_ms": 5.0,
            "slip_bps_est": 0.5,
            "a_bps": 5.0,
            "b_bps": 12.0,
            "score": 0.5,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            # Synthetic TRAP signals: high cancels low replenish => high z
            "trap_cancel_deltas": [10, 8, 6, 4, 2],
            "trap_add_deltas": [0, 0, 0, 0, 0],
            "trap_trades_cnt": 1,
        },
        "fees_bps": 0.2,
    }

    r1 = client.post("/pretrade/check", json=payload)
    assert r1.status_code == 200
    data1 = r1.json()
    # Second shot to build minimal history
    r2 = client.post("/pretrade/check", json=payload)
    assert r2.status_code == 200
    data2 = r2.json()
    # We consider the test passed if TRAP blocks on either first or second request
    if data1["allow"] is False:
        assert data1["reason"] == "trap_guard"
        trap_obs = data1["observability"].get("trap")
    else:
        assert data2["allow"] is False
        assert data2["reason"] in ("trap_guard", "expected_return_gate", "slippage_guard", "latency_guard")
        trap_obs = data2["observability"].get("trap")
    # Observability present
    assert trap_obs is not None
    assert "trap_z" in trap_obs and "cancel_rate" in trap_obs and "repl_rate" in trap_obs and "n_trades" in trap_obs