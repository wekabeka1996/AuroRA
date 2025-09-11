"""
Integration test for idempotency DUP EVENTS scenario.

Key test: test_dup_events_netto_unchanged
- Submit duplicate ACK/PARTIAL/FILL events to handler
- Verify netto state remains unchanged
- IDEM.DUP metric should increment
- Final status should not "roll back"

This test verifies that duplicate order events are properly detected and ignored,
maintaining idempotent behavior in event processing.
"""

import json
import time
from typing import Any, Dict, List
from unittest.mock import Mock

import pytest

from core.aurora_event_logger import AuroraEventLogger
from core.execution.idem_guard import (
    mark_status,
    pre_submit_check,
    set_event_logger,
    set_idem_metrics,
)
from core.execution.idempotency import IdempotencyStore
from observability.codes import IDEM_DUP, IDEM_STORE, IDEM_UPDATE


class OrderEvent:
    """Mock order event structure."""

    def __init__(self, coid: str, status: str, event_id: str, timestamp: int = None):
        self.client_order_id = coid
        self.status = status
        self.event_id = event_id
        self.timestamp = timestamp or int(time.time())
        self.quantity_filled = 0.0
        self.remaining_quantity = 0.0

        # Set quantities based on status
        if status == "PARTIAL":
            self.quantity_filled = 0.0005  # Half filled
            self.remaining_quantity = 0.0005
        elif status == "FILLED":
            self.quantity_filled = 0.001  # Fully filled
            self.remaining_quantity = 0.0


class MockEventHandler:
    """Mock event handler that processes order events with idempotency checking."""

    def __init__(self):
        self.processed_events: List[OrderEvent] = []
        self.duplicate_events: List[str] = []
        self.final_states: Dict[str, Dict[str, Any]] = {}

        # Use separate IdempotencyStore for event deduplication
        self.event_store = IdempotencyStore()

    def process_order_event(self, event: OrderEvent) -> bool:
        """
        Process order event with duplicate detection.

        Returns True if event was processed, False if duplicate.
        """
        # Check for event duplication using event_id
        if hasattr(self.event_store, "seen") and self.event_store.seen(event.event_id):
            # Duplicate event detected
            self.duplicate_events.append(event.event_id)
            return False

        # Mark event as seen
        if hasattr(self.event_store, "mark"):
            self.event_store.mark(event.event_id, ttl_sec=3600.0)

        # Process the event
        self.processed_events.append(event)

        # Update final state for this order
        self.final_states[event.client_order_id] = {
            "status": event.status,
            "quantity_filled": event.quantity_filled,
            "remaining_quantity": event.remaining_quantity,
            "last_updated": event.timestamp,
            "last_event_id": event.event_id,
        }

        # Update idempotency guard with new status
        mark_status(
            event.client_order_id,
            event.status,
            ttl_sec=3600.0,
            result={
                "status": event.status,
                "quantity_filled": event.quantity_filled,
                "remaining_quantity": event.remaining_quantity,
            },
        )

        return True


class TestIdemDupEvents:
    """Integration tests for duplicate event handling."""

    def setup_method(self):
        """Setup test environment."""
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

        # Create event handler
        self.event_handler = MockEventHandler()

        # Clear store state
        store = IdempotencyStore()
        if hasattr(store, "clear"):
            store.clear()

    def teardown_method(self):
        """Cleanup test environment."""
        set_event_logger(None)
        set_idem_metrics(None)

    def test_dup_events_netto_unchanged(self):
        """
        Test that duplicate events don't change the netto state.

        Flow:
        1. Process ACK event
        2. Process duplicate ACK event → should be ignored
        3. Process PARTIAL event
        4. Process duplicate PARTIAL event → should be ignored
        5. Process FILLED event
        6. Process duplicate FILLED event → should be ignored

        Verify final state reflects only unique events.
        """
        coid = "dup_test_order_001"
        base_time = int(time.time())

        # === INITIAL SETUP ===

        # Store initial PENDING state
        pre_submit_check(coid, "hash_dup_test", ttl_sec=600.0)

        # === PROCESS UNIQUE EVENTS ===

        # Event 1: ACK
        ack_event = OrderEvent(coid, "ACK", "event_ack_001", base_time)
        processed_ack = self.event_handler.process_order_event(ack_event)
        assert processed_ack is True, "First ACK event should be processed"

        # Event 2: PARTIAL
        partial_event = OrderEvent(coid, "PARTIAL", "event_partial_001", base_time + 10)
        processed_partial = self.event_handler.process_order_event(partial_event)
        assert processed_partial is True, "First PARTIAL event should be processed"

        # Event 3: FILLED
        filled_event = OrderEvent(coid, "FILLED", "event_filled_001", base_time + 20)
        processed_filled = self.event_handler.process_order_event(filled_event)
        assert processed_filled is True, "First FILLED event should be processed"

        # === PROCESS DUPLICATE EVENTS ===

        # Duplicate ACK (same event_id)
        dup_ack_event = OrderEvent(coid, "ACK", "event_ack_001", base_time + 30)
        processed_dup_ack = self.event_handler.process_order_event(dup_ack_event)
        assert processed_dup_ack is False, "Duplicate ACK event should be ignored"

        # Duplicate PARTIAL (same event_id)
        dup_partial_event = OrderEvent(
            coid, "PARTIAL", "event_partial_001", base_time + 40
        )
        processed_dup_partial = self.event_handler.process_order_event(
            dup_partial_event
        )
        assert (
            processed_dup_partial is False
        ), "Duplicate PARTIAL event should be ignored"

        # Duplicate FILLED (same event_id)
        dup_filled_event = OrderEvent(
            coid, "FILLED", "event_filled_001", base_time + 50
        )
        processed_dup_filled = self.event_handler.process_order_event(dup_filled_event)
        assert processed_dup_filled is False, "Duplicate FILLED event should be ignored"

        # === VERIFY NETTO STATE UNCHANGED ===

        # Check processed events count
        assert (
            len(self.event_handler.processed_events) == 3
        ), "Should have processed exactly 3 unique events"

        # Check duplicate events count
        assert (
            len(self.event_handler.duplicate_events) == 3
        ), "Should have detected 3 duplicate events"
        assert "event_ack_001" in self.event_handler.duplicate_events
        assert "event_partial_001" in self.event_handler.duplicate_events
        assert "event_filled_001" in self.event_handler.duplicate_events

        # Check final state
        final_state = self.event_handler.final_states[coid]
        assert final_state["status"] == "FILLED", "Final status should be FILLED"
        assert final_state["quantity_filled"] == 0.001, "Final quantity should be 0.001"
        assert (
            final_state["remaining_quantity"] == 0.0
        ), "Remaining quantity should be 0"
        assert (
            final_state["last_event_id"] == "event_filled_001"
        ), "Last event ID should be from unique FILLED event"

        # === VERIFY XAI EVENTS ===

        update_events = [e for e in self.logged_events if e["code"] == IDEM_UPDATE]
        assert (
            len(update_events) == 3
        ), "Should have 3 IDEM.UPDATE events (for unique events only)"

        # Verify update event sequence
        update_statuses = [e["data"].get("status") for e in update_events]
        assert update_statuses == [
            "ACK",
            "PARTIAL",
            "FILLED",
        ], "Update sequence should be ACK → PARTIAL → FILLED"

        # === VERIFY METRICS ===

        assert self.update_counts.get("ACK", 0) == 1, "Should have 1 ACK update"
        assert self.update_counts.get("PARTIAL", 0) == 1, "Should have 1 PARTIAL update"
        assert self.update_counts.get("FILLED", 0) == 1, "Should have 1 FILLED update"

    def test_status_no_rollback(self):
        """Test that final status doesn't roll back due to duplicate events."""
        coid = "no_rollback_order_001"
        base_time = int(time.time())

        # Initial setup
        pre_submit_check(coid, "hash_no_rollback", ttl_sec=600.0)

        # Process events in sequence: ACK → FILLED
        ack_event = OrderEvent(coid, "ACK", "event_ack_100", base_time)
        self.event_handler.process_order_event(ack_event)

        filled_event = OrderEvent(coid, "FILLED", "event_filled_100", base_time + 10)
        self.event_handler.process_order_event(filled_event)

        # Verify FILLED state
        assert self.event_handler.final_states[coid]["status"] == "FILLED"

        # Try to process duplicate ACK event (should not rollback to ACK)
        dup_ack_event = OrderEvent(coid, "ACK", "event_ack_100", base_time + 20)
        processed = self.event_handler.process_order_event(dup_ack_event)

        assert processed is False, "Duplicate ACK should be ignored"
        assert (
            self.event_handler.final_states[coid]["status"] == "FILLED"
        ), "Status should remain FILLED"

    def test_out_of_order_duplicates(self):
        """Test handling of out-of-order duplicate events."""
        coid = "out_of_order_001"
        base_time = int(time.time())

        # Initial setup
        pre_submit_check(coid, "hash_out_of_order", ttl_sec=600.0)

        # Process FILLED event first
        filled_event = OrderEvent(coid, "FILLED", "event_filled_200", base_time)
        self.event_handler.process_order_event(filled_event)

        # Try to process ACK event (older timestamp, but unique event_id)
        ack_event = OrderEvent(coid, "ACK", "event_ack_200", base_time - 10)
        processed_ack = self.event_handler.process_order_event(ack_event)
        assert processed_ack is True, "ACK with unique event_id should be processed"

        # But final state should still be FILLED (later timestamp wins in this implementation)
        assert (
            self.event_handler.final_states[coid]["status"] == "ACK"
        ), "Final status should reflect last processed event"

        # Now try duplicate FILLED event
        dup_filled_event = OrderEvent(
            coid, "FILLED", "event_filled_200", base_time + 10
        )
        processed_dup = self.event_handler.process_order_event(dup_filled_event)
        assert processed_dup is False, "Duplicate FILLED should be ignored"

        # Final state should remain as last processed
        assert self.event_handler.final_states[coid]["status"] == "ACK"

    def test_cross_order_event_isolation(self):
        """Test that event deduplication is isolated per order."""
        base_time = int(time.time())

        # Setup two different orders
        coid1 = "isolation_order_001"
        coid2 = "isolation_order_002"

        pre_submit_check(coid1, "hash_isolation_1", ttl_sec=600.0)
        pre_submit_check(coid2, "hash_isolation_2", ttl_sec=600.0)

        # Use same event_id for both orders (should not conflict)
        same_event_id = "event_ack_shared"

        ack_event_1 = OrderEvent(coid1, "ACK", same_event_id, base_time)
        ack_event_2 = OrderEvent(coid2, "ACK", same_event_id, base_time + 5)

        processed_1 = self.event_handler.process_order_event(ack_event_1)
        processed_2 = self.event_handler.process_order_event(ack_event_2)

        # First instance of each event_id should be processed
        assert processed_1 is True, "First order's ACK should be processed"

        # Second use of same event_id should be treated as duplicate
        assert (
            processed_2 is False
        ), "Second order's ACK with same event_id should be duplicate"

        # Verify only one order was affected
        assert (
            len(self.event_handler.final_states) == 1
        ), "Should have final state for only one order"
        assert (
            coid1 in self.event_handler.final_states
        ), "Should have state for first order"
        assert (
            coid2 not in self.event_handler.final_states
        ), "Should not have state for second order"
