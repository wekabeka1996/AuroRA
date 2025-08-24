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
            "slip_bps_est": 1.0,
            "a_bps": 10.0,
            "b_bps": 20.0,
            "score": 0.5,
            "mode_regime": "normal",
            "spread_bps": 5.0,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.anyio
def test_dd_cap_blocks_and_observability_contains_dd_fields():
    with envvar("AURORA_DD_DAY_PCT", "0.5"):
        with TestClient(app) as client:
            payload = base_payload()
            payload["market"]["pnl_today_pct"] = -0.51
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "risk_dd_day_cap"
            obs = data.get("observability", {})
            risk_obs = obs.get("risk", {})
            ctx = risk_obs.get("ctx", {})
            assert ctx.get("dd_cap_pct") == 0.5
            assert ctx.get("dd_used_pct") == pytest.approx(0.51, rel=1e-2)


@pytest.mark.anyio
def test_max_concurrent_blocks_when_equal_to_limit():
    with envvar("AURORA_MAX_CONCURRENT", "1"):
        with TestClient(app) as client:
            payload = base_payload()
            payload["market"]["open_positions"] = 1
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "risk_max_concurrent"


@pytest.mark.anyio
def test_size_scale_propagates_to_response():
    with envvar("AURORA_SIZE_SCALE", "0.05"):
        with TestClient(app) as client:
            payload = base_payload()
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data.get("risk_scale") == pytest.approx(0.05)
            obs = data.get("observability", {})
            rctx = (obs.get("risk") or {}).get("ctx", {})
            assert rctx.get("scaled_notional") == pytest.approx(5.0)


@pytest.mark.anyio
def test_env_override_beats_yaml():
    # Emulate YAML max_concurrent=2 via no env; set env to 1 and block on open_positions=1
    with envvar("AURORA_MAX_CONCURRENT", "1"):
        with TestClient(app) as client:
            payload = base_payload()
            payload["market"]["open_positions"] = 1
            r = client.post("/pretrade/check", json=payload)
            assert r.status_code == 200
            data = r.json()
            assert data["allow"] is False
            assert data["reason"] == "risk_max_concurrent"


@pytest.mark.anyio
def test_ops_set_is_idempotent_and_snapshot_reflects_updates():
    with envvar("AURORA_OPS_TOKEN", "secret"):
        with TestClient(app) as client:
            # Apply same settings twice
            body = {"dd_day_pct": 1.23, "max_concurrent": 7, "size_scale": 0.33}
            r1 = client.post("/risk/set", json=body, headers={"X-OPS-TOKEN": "secret"})
            assert r1.status_code == 200
            r2 = client.post("/risk/set", json=body, headers={"X-OPS-TOKEN": "secret"})
            assert r2.status_code == 200
            snap = client.get("/risk/snapshot", headers={"X-OPS-TOKEN": "secret"})
            assert snap.status_code == 200
            risk = snap.json().get("risk", {})
            assert risk.get("dd_day_pct") == pytest.approx(1.23)
            assert int(risk.get("max_concurrent")) == 7
            assert risk.get("size_scale") == pytest.approx(0.33)
