# tests/unit/test_order_lifecycle.py
"""
Tests for core/order_lifecycle.py
"""

import pytest
from core.order_lifecycle import lifecycle_state_for, TERMINAL


class TestOrderLifecycle:
    """Test order lifecycle state determination."""

    def test_lifecycle_state_for_empty_events(self):
        """Test with empty events list."""
        result = lifecycle_state_for("order1", [])
        assert result == "UNKNOWN"

    def test_lifecycle_state_for_filled_order(self):
        """Test FILLED state has highest priority."""
        events = [
            {"order_id": "order1", "status": "SUBMITTED"},
            {"order_id": "order1", "status": "ACK"},
            {"order_id": "order1", "status": "FILLED"},
            {"order_id": "order1", "status": "CANCELLED"}  # Should be ignored due to FILLED
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "FILLED"

    def test_lifecycle_state_for_cancelled_order(self):
        """Test CANCELLED state priority."""
        events = [
            {"order_id": "order1", "status": "SUBMITTED"},
            {"order_id": "order1", "status": "CANCELLED"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "CANCELLED"

    def test_lifecycle_state_for_expired_order(self):
        """Test EXPIRED state priority."""
        events = [
            {"order_id": "order1", "status": "SUBMITTED"},
            {"order_id": "order1", "status": "EXPIRED"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "EXPIRED"

    def test_lifecycle_state_for_partial_order(self):
        """Test PARTIAL state."""
        events = [
            {"order_id": "order1", "status": "SUBMITTED"},
            {"order_id": "order1", "status": "PARTIAL"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "PARTIAL"

    def test_lifecycle_state_for_ack_order(self):
        """Test ACK state."""
        events = [
            {"order_id": "order1", "status": "SUBMITTED"},
            {"order_id": "order1", "status": "ACK"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "ACK"

    def test_lifecycle_state_for_submitted_order(self):
        """Test SUBMITTED state."""
        events = [
            {"order_id": "order1", "status": "CREATED"},
            {"order_id": "order1", "status": "SUBMITTED"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "SUBMITTED"

    def test_lifecycle_state_for_created_order(self):
        """Test CREATED state."""
        events = [
            {"order_id": "order1", "status": "CREATED"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "CREATED"

    def test_lifecycle_state_for_unknown_order(self):
        """Test UNKNOWN state when no matching events."""
        events = [
            {"order_id": "order1", "status": "CREATED"}
        ]
        result = lifecycle_state_for("order2", events)
        assert result == "UNKNOWN"

    def test_lifecycle_state_for_different_field_names(self):
        """Test with different field names (orderId, state, lifecycle)."""
        events = [
            {"orderId": "order1", "state": "SUBMITTED"},
            {"order_id": "order1", "lifecycle": "FILLED"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "FILLED"

    def test_lifecycle_state_for_mixed_case_status(self):
        """Test with mixed case status values."""
        events = [
            {"order_id": "order1", "status": "submitted"},
            {"order_id": "order1", "status": "filled"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "FILLED"

    def test_lifecycle_state_for_no_status_field(self):
        """Test with events missing status field."""
        events = [
            {"order_id": "order1", "other_field": "value"}
        ]
        result = lifecycle_state_for("order1", events)
        assert result == "UNKNOWN"

    def test_terminal_states_constant(self):
        """Test TERMINAL constant contains expected states."""
        expected = {"FILLED", "CANCELLED", "EXPIRED"}
        assert TERMINAL == expected