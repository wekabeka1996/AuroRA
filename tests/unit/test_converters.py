from __future__ import annotations

from typing import Any, Dict

from core.converters import api_order_to_denied_schema
from api.models import OrderInfo


def test_api_order_to_denied_schema_minimal():
    order = OrderInfo(symbol="BTCUSDT", side="BUY", qty=0.01)
    obs: Dict[str, Any] = {"gate_state": "BLOCK", "reasons": ["spread_bps_too_wide:120.0"], "ts_iso": "2025-08-28T00:00:00Z"}
    d = api_order_to_denied_schema(
        decision_id="abc-123",
        order=order,
        deny_reason="spread_bps_too_wide:120.0",
        reasons=["spread_bps_too_wide:120.0"],
        observability=obs,
    )
    assert d.decision_id == "abc-123"
    assert d.order_id.startswith("deny::")
    assert d.symbol == "BTCUSDT"
    assert d.side == "BUY"
    assert d.qty == 0.01
    assert d.gate_code.startswith("spread_bps_too_wide")
    assert d.snapshot.get("gate_state") == "BLOCK"


def test_api_order_to_denied_schema_dict_input():
    order = {"symbol": "ETHUSDT", "side": "SELL", "qty": 1.5}
    d = api_order_to_denied_schema(
        decision_id="xyz",
        order=order,
        deny_reason="latency_guard",
        reasons=["latency_guard"],
        observability={"gate_state": "BLOCK"},
    )
    assert d.symbol == "ETHUSDT"
    assert d.side == "SELL"
    assert d.qty == 1.5
    assert d.gate_code == "latency_guard"


def test_posttrade_to_success_schema_basic():
    from core.converters import posttrade_to_success_schema
    payload = {
        "symbol": "BTCUSDT",
        "side": "BUY",
        "qty": 0.5,
        "average": 65000.0,
        "filled": 0.5,
        "order_id": "ok123",
    }
    s = posttrade_to_success_schema(payload, decision_id=None, snapshot={"ts_iso": "2025-08-28T01:02:03Z"})
    assert s.order_id == "ok123"
    assert s.symbol == "BTCUSDT"
    assert s.side == "BUY"
    assert s.qty == 0.5
    assert s.avg_price == 65000.0
    assert s.ts_iso == "2025-08-28T01:02:03Z"


def test_posttrade_to_failed_schema_basic():
    from core.converters import posttrade_to_failed_schema
    payload = {
        "symbol": "ETHUSDT",
        "side": "SELL",
        "qty": 2.0,
        "status": "rejected",
        "error_code": "EXCHANGE_ERROR",
        "error_msg": "something",
        "order_id": "rej1",
    }
    f = posttrade_to_failed_schema(payload, decision_id="abc")
    assert f.decision_id == "abc"
    assert f.order_id == "rej1"
    assert f.error_code == "EXCHANGE_ERROR"
    assert f.final_status.lower() == "rejected"
