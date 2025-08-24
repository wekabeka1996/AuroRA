from __future__ import annotations

import os
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from api.service import app


@contextmanager
def envvar(k: str, v: str):
    old = os.environ.get(k)
    os.environ[k] = v
    try:
        yield
    finally:
        if old is None:
            del os.environ[k]
        else:
            os.environ[k] = old


def base_payload():
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 1.0, "base_notional": 100.0},
        "market": {
            "latency_ms": 5,
            "slip_bps_est": 0.5,
            "a_bps": 10.0,
            "b_bps": 20.0,
            "score": 0.5,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            # Trap inputs neutral by default
            "trap_cancel_deltas": [0.0, 0.0],
            "trap_add_deltas": [0.0, 0.0],
            "trap_trades_cnt": 10,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_only_trap_blocks_when_above_threshold():
    with envvar("TRAP_GUARD", "on"):
        with TestClient(app) as client:
            payload = base_payload()
            # Make trap trigger: large cancel, tiny add
            payload["market"]["trap_cancel_deltas"] = [100.0, 100.0]
            payload["market"]["trap_add_deltas"] = [0.1, 0.1]
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] in ("trap_guard", "trap_guard_score")
            reasons = (data.get("observability", {}).get("reasons") or [])
            # Ensure only trap reason present (no expected_return/risk/sprt)
            assert all("expected_return" not in x for x in reasons)
            assert all("sprt" not in x for x in reasons)


@pytest.mark.anyio
def test_expected_return_blocks_before_risk_and_sprt():
    with TestClient(app) as client:
        payload = base_payload()
        # Force expected return to fail: low b_bps and high fees/slip
        payload["market"]["b_bps"] = 1.0
        payload["fees_bps"] = 10.0
        payload["market"]["slip_bps_est"] = 20.0
        r = client.post("/pretrade/check", json=payload)
        assert r.status_code == 200
        data = r.json()
        assert data["allow"] is False
        assert data["reason"] == "expected_return_gate"
        reasons = (data.get("observability", {}).get("reasons") or [])
        # Risk/SRPT should not have been deciding factors
        assert all("risk_" not in x for x in reasons)
        assert all("sprt" not in x for x in reasons)


@pytest.mark.anyio
def test_slippage_before_er_profile_blocks_by_slip():
    # When PRETRADE_ORDER_PROFILE=slip_before_er, slippage should decide first
    with envvar("PRETRADE_ORDER_PROFILE", "slip_before_er"):
        with TestClient(app) as client:
            payload = base_payload()
            # Make slippage definitely fail (high slip, reasonable b_bps)
            payload["market"]["b_bps"] = 10.0
            payload["market"]["slip_bps_est"] = 100.0
            # fees kept modest so ER might have passed otherwise
            payload["fees_bps"] = 0.1
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "slippage_guard"


@pytest.mark.anyio
def test_risk_blocks_when_expected_return_passes():
    with envvar("AURORA_DD_DAY_PCT", "0.5"):
        with TestClient(app) as client:
            payload = base_payload()
            payload["market"]["pnl_today_pct"] = -1.0
            # Ensure expected return passes (boost b_bps)
            payload["market"]["b_bps"] = 50.0
            payload["fees_bps"] = 0.1
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "risk_dd_day_cap"
            reasons = (data.get("observability", {}).get("reasons") or [])
            # Should not show sprt reasons
            assert all("sprt" not in x for x in reasons)
