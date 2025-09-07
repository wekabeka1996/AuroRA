from __future__ import annotations

from typing import Any, Dict
from unittest.mock import Mock

import pytest

from core.converters import (
    api_order_to_denied_schema,
    posttrade_to_success_schema,
    posttrade_to_failed_schema,
    _get_ts_iso,
)
from api.models import OrderInfo


class TestApiOrderToDeniedSchema:
    """Test api_order_to_denied_schema function."""

    def test_api_order_to_denied_schema_minimal(self):
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

    def test_api_order_to_denied_schema_dict_input(self):
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

    def test_api_order_to_denied_schema_empty_order_dict(self):
        """Test with empty dict order input."""
        order = {}
        d = api_order_to_denied_schema(
            decision_id="test-123",
            order=order,
            deny_reason="test_reason",
            reasons=["test_reason"],
            observability=None,
        )
        assert d.symbol == ""
        assert d.side == ""
        assert d.qty == 0.0
        assert d.gate_code == "test_reason"
        assert d.snapshot == {}

    def test_api_order_to_denied_schema_none_observability(self):
        """Test with None observability."""
        order = {"symbol": "BTCUSDT", "side": "BUY", "qty": 0.01}
        d = api_order_to_denied_schema(
            decision_id="test-123",
            order=order,
            deny_reason="test_reason",
            reasons=None,
            observability=None,
        )
        assert d.snapshot == {}
        assert d.gate_detail["reasons"] == []

    def test_api_order_to_denied_schema_orderinfo_model_dump_fails(self):
        """Test when OrderInfo.model_dump() fails."""
        order = Mock(spec=OrderInfo)
        order.model_dump.side_effect = Exception("Dump failed")
        d = api_order_to_denied_schema(
            decision_id="test-123",
            order=order,
            deny_reason="test_reason",
            reasons=["test_reason"],
            observability={"ts_iso": "2025-01-01T00:00:00Z"},
        )
        assert d.symbol == ""
        assert d.side == ""
        assert d.qty == 0.0
        assert d.ts_iso == "2025-01-01T00:00:00Z"

    def test_api_order_to_denied_schema_missing_ts_iso(self):
        """Test when ts_iso is missing from observability."""
        order = {"symbol": "BTCUSDT", "side": "BUY", "qty": 0.01}
        d = api_order_to_denied_schema(
            decision_id="test-123",
            order=order,
            deny_reason="test_reason",
            reasons=["test_reason"],
            observability={"gate_state": "BLOCK"},
        )
        assert d.ts_iso == ""

    def test_api_order_to_denied_schema_invalid_qty(self):
        """Test with invalid qty that can't be converted to float."""
        order = {"symbol": "BTCUSDT", "side": "BUY", "qty": "invalid"}
        with pytest.raises(ValueError, match="could not convert string to float"):
            api_order_to_denied_schema(
                decision_id="test-123",
                order=order,
                deny_reason="test_reason",
                reasons=["test_reason"],
                observability=None,
            )


class TestPosttradeToSuccessSchema:
    """Test posttrade_to_success_schema function."""

    def test_posttrade_to_success_schema_basic(self):
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

    def test_posttrade_to_success_schema_with_decision_id(self):
        """Test with decision_id provided."""
        payload = {
            "symbol": "ETHUSDT",
            "side": "SELL",
            "qty": 1.0,
            "price": 3000.0,
            "order_id": "test123",
        }
        s = posttrade_to_success_schema(payload, decision_id="dec-123", snapshot=None)
        assert s.decision_id == "dec-123"
        assert s.avg_price == 3000.0
        assert s.ts_iso == ""

    def test_posttrade_to_success_schema_empty_payload(self):
        """Test with empty payload."""
        s = posttrade_to_success_schema({}, decision_id="test", snapshot=None)
        assert s.order_id == ""
        assert s.symbol == ""
        assert s.side == ""
        assert s.qty == 0.0
        assert s.avg_price == 0.0
        assert s.fees == 0.0
        assert s.filled_pct == 0.0

    def test_posttrade_to_success_schema_none_payload(self):
        """Test with None payload."""
        s = posttrade_to_success_schema(None, decision_id="test", snapshot=None)
        assert s.order_id == ""
        assert s.symbol == ""
        assert s.qty == 0.0

    def test_posttrade_to_success_schema_alternative_field_names(self):
        """Test with alternative field names (amount, avg_price, id)."""
        payload = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "amount": 2.0,
            "avg_price": 50000.0,
            "id": "alt123",
            "fee": {"cost": 10.0},
        }
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.qty == 2.0
        assert s.avg_price == 50000.0
        assert s.order_id == "alt123"
        assert s.fees == 10.0

    def test_posttrade_to_success_schema_filled_pct_calculation(self):
        """Test filled_pct calculation logic."""
        # When filled > 0, filled_pct should be 1.0 if not provided
        payload = {"filled": 0.5, "qty": 0.5}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.filled_pct == 1.0

        # When filled = 0, filled_pct should be 0.0
        payload = {"filled": 0.0, "qty": 0.5}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.filled_pct == 0.0

        # When filled_pct is explicitly provided AND filled > 0, use filled_pct
        payload = {"filled_pct": 0.75, "filled": 0.1}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.filled_pct == 0.75

        # When filled_pct is explicitly provided but filled <= 0, use 0.0
        payload = {"filled_pct": 0.75, "filled": 0.0}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.filled_pct == 0.0

    def test_posttrade_to_success_schema_fee_handling(self):
        """Test different fee formats."""
        # Numeric fee
        payload = {"fee": 5.0}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.fees == 5.0

        # Dict fee with cost
        payload = {"fee": {"cost": 7.5}}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.fees == 7.5

        # Invalid fee dict
        payload = {"fee": {"invalid": "value"}}
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.fees == 0.0

    def test_posttrade_to_success_schema_exchange_fields(self):
        """Test exchange-related fields."""
        payload = {
            "clientOrderId": "client123",
            "orderId": "exchange456",
            "exchange_ts": "2025-01-01T12:00:00Z",
        }
        s = posttrade_to_success_schema(payload, decision_id=None, snapshot=None)
        assert s.client_order_id == "client123"
        assert s.exchange_order_id == "exchange456"
        assert s.exchange_ts == "2025-01-01T12:00:00Z"


class TestPosttradeToFailedSchema:
    """Test posttrade_to_failed_schema function."""

    def test_posttrade_to_failed_schema_basic(self):
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

    def test_posttrade_to_failed_schema_with_snapshot(self):
        """Test with snapshot provided."""
        payload = {"order_id": "fail123", "error_code": "TIMEOUT"}
        f = posttrade_to_failed_schema(payload, decision_id="dec-456", snapshot={"ts_iso": "2025-01-01T10:00:00Z"})
        assert f.ts_iso == "2025-01-01T10:00:00Z"
        assert f.decision_id == "dec-456"
        assert f.error_code == "TIMEOUT"

    def test_posttrade_to_failed_schema_empty_payload(self):
        """Test with empty payload."""
        f = posttrade_to_failed_schema({}, decision_id=None, snapshot=None)
        assert f.order_id == ""
        assert f.symbol == ""
        assert f.error_code == ""
        assert f.error_msg == ""
        assert f.attempts == 1
        assert f.final_status == ""

    def test_posttrade_to_failed_schema_none_payload(self):
        """Test with None payload."""
        f = posttrade_to_failed_schema(None, decision_id=None, snapshot=None)
        assert f.order_id == ""
        assert f.qty == 0.0

    def test_posttrade_to_failed_schema_alternative_field_names(self):
        """Test with alternative field names."""
        payload = {
            "id": "alt456",
            "amount": 3.0,
            "reason_detail": "connection failed",
            "clientOrderId": "client789",
            "orderId": "exch101",
            "attempts": 3,
            "final_status": "cancelled",
        }
        f = posttrade_to_failed_schema(payload, decision_id=None, snapshot=None)
        assert f.order_id == "alt456"
        assert f.qty == 3.0
        assert f.error_msg == "connection failed"
        assert f.client_order_id == "client789"
        assert f.exchange_order_id == "exch101"
        assert f.attempts == 3
        assert f.final_status == "cancelled"

    def test_posttrade_to_failed_schema_invalid_attempts(self):
        """Test with invalid attempts value."""
        payload = {"attempts": "invalid"}
        with pytest.raises(ValueError, match="invalid literal for int"):
            posttrade_to_failed_schema(payload, decision_id=None, snapshot=None)


class TestGetTsIso:
    """Test _get_ts_iso helper function."""

    def test_get_ts_iso_with_valid_ts(self):
        """Test with valid ts_iso in snapshot."""
        snapshot = {"ts_iso": "2025-01-01T12:00:00Z"}
        result = _get_ts_iso(snapshot)
        assert result == "2025-01-01T12:00:00Z"

    def test_get_ts_iso_with_none_snapshot(self):
        """Test with None snapshot."""
        result = _get_ts_iso(None)
        assert result == ""

    def test_get_ts_iso_with_empty_snapshot(self):
        """Test with empty snapshot."""
        result = _get_ts_iso({})
        assert result == ""

    def test_get_ts_iso_with_none_ts_iso(self):
        """Test with None ts_iso value."""
        snapshot = {"ts_iso": None}
        result = _get_ts_iso(snapshot)
        assert result == ""

    def test_get_ts_iso_with_exception(self):
        """Test when accessing ts_iso raises exception."""
        snapshot = Mock()
        snapshot.get.side_effect = Exception("Access error")
        result = _get_ts_iso(snapshot)
        assert result == ""

    def test_get_ts_iso_with_non_string_ts_iso(self):
        """Test with non-string ts_iso value."""
        snapshot = {"ts_iso": 12345}
        result = _get_ts_iso(snapshot)
        assert result == "12345"
