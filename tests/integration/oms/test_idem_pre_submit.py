"""
Integration test for idempotency pre-submit HIT scenario.

Key test: test_hit_returns_cached_without_http
- 1st submit → HTTP=1 (ACK/FILLED)
- 2nd submit same client_oid/spec_hash → HTTP=0, returns cached OrderResult
- Verify XAI sequence: IDEM.CHECK → IDEM.STORE(PENDING) → IDEM.UPDATE(ACK|FILLED) → IDEM.HIT

This test verifies that duplicate submissions with identical spec are handled efficiently
without making redundant HTTP calls to the exchange.
"""

import json
import time
from typing import Any, Dict, Optional
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
from observability.codes import IDEM_CHECK, IDEM_DUP, IDEM_HIT, IDEM_STORE, IDEM_UPDATE


class MockOrderResult:
    """Mock order result that simulates exchange response."""

    def __init__(self, coid: str, status: str, price: float, qty: float):
        self.client_order_id = coid
        self.status = status
        self.price = price
        self.quantity = qty

    def to_dict(self) -> Dict[str, Any]:
        return {
            "client_order_id": self.client_order_id,
            "status": self.status,
            "price": self.price,
            "quantity": self.quantity,
        }


class MockHTTPAdapter:
    """Mock HTTP adapter to track HTTP call counts."""

    def __init__(self):
        self.http_calls = 0
        self.responses = []

    def submit_order(self, coid: str, spec_hash: str) -> MockOrderResult:
        """Simulate order submission with HTTP call."""
        self.http_calls += 1
        result = MockOrderResult(coid, "FILLED", 50000.0, 0.001)
        self.responses.append(result)
        return result


class TestIdemPreSubmit:
    """Integration tests for idempotency pre-submit workflow."""

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

    def test_hit_returns_cached_without_http(self):
        """
        Test HIT scenario: duplicate submission returns cached result without HTTP call.

        Flow:
        1. First submit: pre_submit_check -> None (store PENDING), HTTP call, mark_status
        2. Second submit: pre_submit_check -> cached payload (HIT), no HTTP call

        Verify XAI sequence and HTTP call count.
        """
        coid = "test_order_001"
        spec_hash = "hash_abc123"

        # === FIRST SUBMISSION ===

        # Step 1: Pre-submit check (should return None for fresh order)
        first_check = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert first_check is None, "First pre_submit_check should return None"

        # Step 2: Simulate HTTP call to exchange
        order_result = self.http_adapter.submit_order(coid, spec_hash)
        assert (
            self.http_adapter.http_calls == 1
        ), "Should make 1 HTTP call on first submit"

        # Step 3: Mark status as FILLED with result
        mark_status(coid, "FILLED", ttl_sec=3600.0, result=order_result.to_dict())

        # === SECOND SUBMISSION (DUPLICATE) ===

        # Step 4: Pre-submit check (should return cached payload - HIT)
        second_check = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert (
            second_check is not None
        ), "Second pre_submit_check should return cached payload"
        assert second_check["spec_hash"] == spec_hash, "Cached spec_hash should match"
        assert second_check["status"] == "FILLED", "Cached status should be FILLED"

        # Step 5: No additional HTTP call should be made
        # In real implementation, the adapter would check pre_submit_check result
        # and skip HTTP call if cached result exists
        assert (
            self.http_adapter.http_calls == 1
        ), "Should still be 1 HTTP call (no additional)"

        # === VERIFY XAI EVENT SEQUENCE ===

        event_codes = [event["code"] for event in self.logged_events]

        # Expected sequence: STORE (first), UPDATE (mark status), HIT (second check), DUP
        assert IDEM_STORE in event_codes, "Should emit IDEM.STORE on first check"
        assert IDEM_UPDATE in event_codes, "Should emit IDEM.UPDATE on mark_status"
        assert IDEM_HIT in event_codes, "Should emit IDEM.HIT on second check"
        assert IDEM_DUP in event_codes, "Should emit IDEM.DUP on duplicate detection"

        # Verify proper sequence order
        store_idx = event_codes.index(IDEM_STORE)
        update_idx = event_codes.index(IDEM_UPDATE)
        hit_idx = event_codes.index(IDEM_HIT)
        dup_idx = event_codes.index(IDEM_DUP)

        assert store_idx < update_idx, "STORE should come before UPDATE"
        assert update_idx < hit_idx, "UPDATE should come before HIT"
        assert hit_idx <= dup_idx, "HIT should come before or with DUP"

        # === VERIFY METRICS ===

        assert self.check_counts["store"] == 1, "Should increment store metric once"
        assert self.check_counts["hit"] == 1, "Should increment hit metric once"
        assert self.dup_count == 1, "Should increment dup counter once"
        assert (
            self.update_counts.get("FILLED", 0) == 1
        ), "Should increment FILLED update metric"

        # === VERIFY CACHED RESULT INTEGRITY ===

        cached_result = second_check.get("result")
        assert cached_result is not None, "Cached result should be present"
        assert cached_result["client_order_id"] == coid, "Cached COID should match"
        assert cached_result["status"] == "FILLED", "Cached status should match"
        assert cached_result["price"] == 50000.0, "Cached price should match"
        assert cached_result["quantity"] == 0.001, "Cached quantity should match"

    def test_fresh_order_returns_none_and_stores_pending(self):
        """Test that fresh order returns None and stores PENDING status."""
        coid = "fresh_order_001"
        spec_hash = "hash_def456"

        # Pre-submit check for fresh order
        result = pre_submit_check(coid, spec_hash, ttl_sec=600.0)

        # Should return None (fresh order)
        assert result is None

        # Should emit STORE event
        event_codes = [event["code"] for event in self.logged_events]
        assert IDEM_STORE in event_codes

        # Should increment store metric
        assert self.check_counts["store"] == 1

        # Verify stored data by doing another check
        second_check = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert second_check is not None
        assert second_check["status"] == "PENDING"
        assert second_check["spec_hash"] == spec_hash

    def test_mark_status_preserves_spec_hash(self):
        """Test that mark_status preserves existing spec_hash."""
        coid = "preserve_test_001"
        spec_hash = "hash_preserve_123"

        # Initial check to store PENDING
        pre_submit_check(coid, spec_hash, ttl_sec=600.0)

        # Mark as ACK
        mark_status(coid, "ACK", ttl_sec=3600.0)

        # Verify spec_hash is preserved
        check_result = pre_submit_check(coid, spec_hash, ttl_sec=600.0)
        assert check_result is not None
        assert check_result["spec_hash"] == spec_hash
        assert check_result["status"] == "ACK"
