"""
Integration test for idempotency CONFLICT scenario.

Key test: test_conflict_raises_409_and_no_http
- Same client_oid but different price → different spec_hash
- Should raise IdempotencyConflict (409)
- No HTTP call should be made
- XAI should emit IDEM.CONFLICT with prev_spec_hash/new_spec_hash

This test verifies that conflicting submissions are properly detected and rejected
without making HTTP calls to the exchange.
"""

import json
import time
from typing import Any, Dict
from unittest.mock import MagicMock, Mock

import pytest

from core.aurora_event_logger import AuroraEventLogger
from core.execution.idem_guard import (
    IdempotencyConflict,
    mark_status,
    pre_submit_check,
    set_event_logger,
    set_idem_metrics,
)
from core.execution.idempotency import IdempotencyStore
from observability.codes import IDEM_CONFLICT, IDEM_STORE, IDEM_UPDATE


class MockHTTPAdapter:
    """Mock HTTP adapter to track HTTP call counts."""

    def __init__(self):
        self.http_calls = 0
        self.responses = []

    def submit_order(self, coid: str, spec_hash: str, price: float, qty: float):
        """Simulate order submission with HTTP call."""
        self.http_calls += 1
        result = {
            "client_order_id": coid,
            "status": "ACK",
            "price": price,
            "quantity": qty,
        }
        self.responses.append(result)
        return result


class TestIdemConflict:
    """Integration tests for idempotency conflict detection."""

    def setup_method(self):
        """Setup test environment with mocks."""
        # Mock event logger
        self.mock_logger = Mock(spec=AuroraEventLogger)
        self.logged_events = []

        def capture_event(code: str, data: Dict[str, Any]):
            self.logged_events.append({"code": code, "data": data})

        self.mock_logger.emit.side_effect = capture_event
        set_event_logger(self.mock_logger)

        # Mock metrics
        self.mock_metrics = Mock()
        self.check_counts = {"hit": 0, "store": 0, "conflict": 0}
        self.dup_count = 0
        self.update_counts = {}

        def inc_check(reason: str):
            self.check_counts[reason] = self.check_counts.get(reason, 0) + 1

        def inc_dup_submit():
            nonlocal self
            self.dup_count += 1

        def inc_update(status: str):
            self.update_counts[status] = self.update_counts.get(status, 0) + 1

        self.mock_metrics.inc_check.side_effect = inc_check
        self.mock_metrics.inc_dup_submit.side_effect = inc_dup_submit
        self.mock_metrics.inc_update.side_effect = inc_update
        set_idem_metrics(self.mock_metrics)

        # Mock HTTP adapter
        self.http_adapter = MockHTTPAdapter()

        # Clear store state
        store = IdempotencyStore()
        if hasattr(store, "clear"):
            store.clear()

    def teardown_method(self):
        """Cleanup test environment."""
        set_event_logger(None)
        set_idem_metrics(None)

    def test_conflict_raises_409_and_no_http(self):
        """
        Test CONFLICT scenario: same COID with different spec raises IdempotencyConflict.

        Flow:
        1. First submit: COID + spec_hash_1 → stores PENDING
        2. Second submit: same COID + spec_hash_2 → raises IdempotencyConflict
        3. No HTTP call for second submit
        4. XAI emits IDEM.CONFLICT
        """
        coid = "conflict_order_001"
        spec_hash_1 = "hash_price_50000"  # Original order at $50,000
        spec_hash_2 = "hash_price_51000"  # Conflicting order at $51,000

        # === FIRST SUBMISSION ===

        # Step 1: Pre-submit check for original order (should store PENDING)
        first_check = pre_submit_check(coid, spec_hash_1, ttl_sec=600.0)
        assert first_check is None, "First pre_submit_check should return None"

        # Step 2: Simulate successful HTTP call and mark as ACK
        first_result = self.http_adapter.submit_order(coid, spec_hash_1, 50000.0, 0.001)
        assert (
            self.http_adapter.http_calls == 1
        ), "Should make 1 HTTP call on first submit"

        mark_status(coid, "ACK", ttl_sec=3600.0, result=first_result)

        # === CONFLICTING SUBMISSION ===

        # Step 3: Pre-submit check with different spec_hash (should raise conflict)
        with pytest.raises(IdempotencyConflict) as exc_info:
            pre_submit_check(coid, spec_hash_2, ttl_sec=600.0)

        # Verify exception message
        assert "IDEMPOTENCY_CONFLICT" in str(exc_info.value)
        assert "same client_order_id with different spec" in str(exc_info.value)

        # Step 4: No additional HTTP call should be made
        assert (
            self.http_adapter.http_calls == 1
        ), "Should still be 1 HTTP call (no conflict call)"

        # === VERIFY XAI EVENT SEQUENCE ===

        event_codes = [event["code"] for event in self.logged_events]

        # Expected sequence: STORE (first), UPDATE (mark status), CONFLICT (second check)
        assert IDEM_STORE in event_codes, "Should emit IDEM.STORE on first check"
        assert IDEM_UPDATE in event_codes, "Should emit IDEM.UPDATE on mark_status"
        assert (
            IDEM_CONFLICT in event_codes
        ), "Should emit IDEM.CONFLICT on conflicting check"

        # Verify proper sequence order
        store_idx = event_codes.index(IDEM_STORE)
        update_idx = event_codes.index(IDEM_UPDATE)
        conflict_idx = event_codes.index(IDEM_CONFLICT)

        assert store_idx < update_idx, "STORE should come before UPDATE"
        assert update_idx < conflict_idx, "UPDATE should come before CONFLICT"

        # Verify conflict event data
        conflict_events = [e for e in self.logged_events if e["code"] == IDEM_CONFLICT]
        assert len(conflict_events) == 1, "Should have exactly one CONFLICT event"
        conflict_data = conflict_events[0]["data"]
        assert (
            conflict_data["cid"] == coid
        ), "CONFLICT event should contain correct COID"

        # === VERIFY METRICS ===

        assert self.check_counts["store"] == 1, "Should increment store metric once"
        assert (
            self.check_counts["conflict"] == 1
        ), "Should increment conflict metric once"
        assert self.check_counts["hit"] == 0, "Should not increment hit metric"
        assert self.dup_count == 0, "Should not increment dup counter"
        assert (
            self.update_counts.get("ACK", 0) == 1
        ), "Should increment ACK update metric"

    def test_same_spec_hash_no_conflict(self):
        """Test that same COID + same spec_hash does not raise conflict."""
        coid = "no_conflict_order_001"
        spec_hash = "hash_same_spec"

        # First submission
        first_check = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert first_check is None

        mark_status(coid, "FILLED", ttl_sec=3600.0)

        # Second submission with same spec - should be HIT, not conflict
        second_check = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert second_check is not None
        assert second_check["status"] == "FILLED"
        assert second_check["spec_hash"] == spec_hash

        # Should not have conflict event
        event_codes = [event["code"] for event in self.logged_events]
        assert IDEM_CONFLICT not in event_codes
        assert self.check_counts["conflict"] == 0

    def test_conflict_after_various_statuses(self):
        """Test conflict detection works after various order statuses."""
        coid = "status_conflict_001"
        spec_hash_1 = "hash_original"
        spec_hash_2 = "hash_conflicting"

        # Test conflict after PENDING status
        pre_submit_check(coid, spec_hash_1, ttl_sec=600.0)  # stores PENDING

        with pytest.raises(IdempotencyConflict):
            pre_submit_check(coid, spec_hash_2, ttl_sec=600.0)

        # Clear and test conflict after ACK status
        store = IdempotencyStore()
        if hasattr(store, "clear"):
            store.clear()
        self.logged_events.clear()

        pre_submit_check(coid, spec_hash_1, ttl_sec=600.0)
        mark_status(coid, "ACK", ttl_sec=3600.0)

        with pytest.raises(IdempotencyConflict):
            pre_submit_check(coid, spec_hash_2, ttl_sec=600.0)

        # Clear and test conflict after FILLED status
        if hasattr(store, "clear"):
            store.clear()
        self.logged_events.clear()

        pre_submit_check(coid, spec_hash_1, ttl_sec=600.0)
        mark_status(coid, "FILLED", ttl_sec=3600.0)

        with pytest.raises(IdempotencyConflict):
            pre_submit_check(coid, spec_hash_2, ttl_sec=600.0)

    def test_conflict_metrics_accumulate(self):
        """Test that conflict metrics properly accumulate over multiple conflicts."""
        base_coid = "multi_conflict"
        spec_hash_1 = "hash_original"
        spec_hash_2 = "hash_conflict_1"
        spec_hash_3 = "hash_conflict_2"

        # Store original
        pre_submit_check(f"{base_coid}_1", spec_hash_1, ttl_sec=600.0)
        pre_submit_check(f"{base_coid}_2", spec_hash_1, ttl_sec=600.0)

        # Multiple conflicts
        with pytest.raises(IdempotencyConflict):
            pre_submit_check(f"{base_coid}_1", spec_hash_2, ttl_sec=600.0)

        with pytest.raises(IdempotencyConflict):
            pre_submit_check(f"{base_coid}_2", spec_hash_3, ttl_sec=600.0)

        # Verify metrics
        assert self.check_counts["store"] == 2, "Should have 2 store operations"
        assert self.check_counts["conflict"] == 2, "Should have 2 conflicts"

        # Verify events
        conflict_events = [e for e in self.logged_events if e["code"] == IDEM_CONFLICT]
        assert len(conflict_events) == 2, "Should have 2 CONFLICT events"
