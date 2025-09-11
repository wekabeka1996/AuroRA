"""
Unit tests for guard status monotonicity and lifecycle management.

Tests coverage for status transition validation in core/execution/idem_guard.py.
"""

import time
from unittest.mock import Mock, patch

import pytest

from core.execution.idem_guard import IdempotencyConflict, mark_status, pre_submit_check


class TestGuardStatusMonotonicity:
    """Test guard status monotonicity and lifecycle management."""

    def test_status_monotonicity_valid_transitions(self):
        """Test valid status transitions are allowed."""
        mock_store = Mock()

        # Valid transition sequence: SUBMITTED -> PENDING -> PARTIALLY_FILLED -> FILLED
        valid_transitions = [
            ("SUBMITTED", "PENDING"),
            ("PENDING", "PARTIALLY_FILLED"),
            ("PARTIALLY_FILLED", "FILLED"),
            ("SUBMITTED", "FILLED"),  # Direct transition also valid
            ("PENDING", "FILLED"),  # Skip intermediate also valid
        ]

        for current_status, new_status in valid_transitions:
            mock_store.reset_mock()
            mock_store.get.return_value = current_status

            # Should allow valid transition
            try:
                mark_status("test_id", new_status, mock_store)
                # Should call put to update status
                mock_store.put.assert_called()
            except Exception as e:
                pytest.fail(
                    f"Valid transition {current_status} -> {new_status} should be allowed: {e}"
                )

    def test_status_monotonicity_invalid_backwards_transitions(self):
        """Test invalid backwards transitions are blocked."""
        mock_store = Mock()

        # Invalid backwards transitions
        invalid_transitions = [
            ("FILLED", "PARTIALLY_FILLED"),
            ("FILLED", "PENDING"),
            ("FILLED", "SUBMITTED"),
            ("PARTIALLY_FILLED", "SUBMITTED"),
            ("PENDING", "SUBMITTED"),
        ]

        for current_status, new_status in invalid_transitions:
            mock_store.reset_mock()
            mock_store.get.return_value = current_status

            # Should block invalid backwards transition
            with pytest.raises((IdempotencyConflict, ValueError)) as exc_info:
                mark_status("test_id", new_status, mock_store)

            assert (
                "backwards" in str(exc_info.value).lower()
                or "invalid" in str(exc_info.value).lower()
            ), f"Should block backwards transition {current_status} -> {new_status}"

    def test_status_monotonicity_same_status_idempotent(self):
        """Test setting same status multiple times is idempotent."""
        mock_store = Mock()

        statuses_to_test = [
            "SUBMITTED",
            "PENDING",
            "PARTIALLY_FILLED",
            "FILLED",
            "CANCELLED",
        ]

        for status in statuses_to_test:
            mock_store.reset_mock()
            mock_store.get.return_value = status

            # Setting same status should be idempotent (no error)
            try:
                mark_status("test_id", status, mock_store)
                # Should still call put (for timestamp update or other metadata)
                mock_store.put.assert_called()
            except Exception as e:
                pytest.fail(
                    f"Same status {status} -> {status} should be idempotent: {e}"
                )

    def test_status_lifecycle_with_cancellation(self):
        """Test cancellation can happen from any non-terminal state."""
        mock_store = Mock()

        # Cancellation should be allowed from any non-terminal state
        cancellable_states = ["SUBMITTED", "PENDING", "PARTIALLY_FILLED"]

        for current_status in cancellable_states:
            mock_store.reset_mock()
            mock_store.get.return_value = current_status

            # Should allow cancellation
            try:
                mark_status("test_id", "CANCELLED", mock_store)
                mock_store.put.assert_called()
            except Exception as e:
                pytest.fail(
                    f"Cancellation from {current_status} should be allowed: {e}"
                )

    def test_status_lifecycle_terminal_states_immutable(self):
        """Test terminal states cannot be changed."""
        mock_store = Mock()

        terminal_states = ["FILLED", "CANCELLED", "REJECTED"]

        for terminal_status in terminal_states:
            for new_status in ["PENDING", "PARTIALLY_FILLED", "SUBMITTED"]:
                mock_store.reset_mock()
                mock_store.get.return_value = terminal_status

                # Should block changes from terminal states
                with pytest.raises((IdempotencyConflict, ValueError)) as exc_info:
                    mark_status("test_id", new_status, mock_store)

                assert (
                    "terminal" in str(exc_info.value).lower()
                    or "final" in str(exc_info.value).lower()
                ), f"Should block change from terminal state {terminal_status} -> {new_status}"

    def test_status_validation_unknown_status(self):
        """Test handling of unknown/invalid status values."""
        mock_store = Mock()
        mock_store.get.return_value = "PENDING"

        # Unknown status should be handled appropriately
        unknown_statuses = ["UNKNOWN_STATUS", "INVALID", "", None, 123]

        for unknown_status in unknown_statuses:
            mock_store.reset_mock()

            # Should either reject unknown status or handle gracefully
            try:
                mark_status("test_id", unknown_status, mock_store)
                # If accepted, should still call put
                mock_store.put.assert_called()
            except (ValueError, TypeError) as e:
                # Acceptable to reject unknown statuses
                assert "unknown" in str(e).lower() or "invalid" in str(e).lower()

    def test_status_timestamp_monotonicity(self):
        """Test status updates include monotonic timestamps."""
        mock_store = Mock()
        mock_store.get.return_value = "PENDING"

        # Mock time progression
        with patch("time.time") as mock_time:
            mock_time.side_effect = [1000.0, 1001.0, 1002.0]  # Increasing timestamps

            mark_status("test_id", "PARTIALLY_FILLED", mock_store)

            # Should include timestamp in update
            mock_store.put.assert_called()
            call_args = mock_store.put.call_args

            # Check if timestamp information is included
            if len(call_args[0]) > 2:  # key, value, ttl
                # Check if timestamp or time-related info is passed
                args_str = str(call_args)
                assert any(
                    keyword in args_str.lower()
                    for keyword in ["time", "timestamp", "1001"]
                ), "Should include timestamp information"

    def test_concurrent_status_updates_last_writer_wins(self):
        """Test concurrent status updates follow last-writer-wins semantics."""
        import threading
        import time

        mock_store = Mock()

        # Setup concurrent update tracking
        update_order = []
        original_put = mock_store.put

        def tracked_put(*args, **kwargs):
            update_order.append(
                (threading.current_thread().ident, args[1], time.time())
            )
            return original_put(*args, **kwargs)

        mock_store.put.side_effect = tracked_put
        mock_store.get.return_value = "PENDING"

        results = []
        exceptions = []

        def worker(status, delay):
            try:
                time.sleep(delay)
                mark_status("test_id", status, mock_store)
                results.append(status)
            except Exception as e:
                exceptions.append(e)

        # Start concurrent workers with different delays
        workers = [
            threading.Thread(target=worker, args=("PARTIALLY_FILLED", 0.01)),
            threading.Thread(target=worker, args=("FILLED", 0.02)),
            threading.Thread(
                target=worker, args=("CANCELLED", 0.03)
            ),  # This might conflict
        ]

        for w in workers:
            w.start()
        for w in workers:
            w.join()

        # At least some updates should succeed
        assert len(results) > 0, "Some status updates should succeed"
        assert len(update_order) > 0, "Should track update order"

        # Check monotonic timestamps in updates
        if len(update_order) > 1:
            timestamps = [t[2] for t in update_order]
            assert timestamps == sorted(
                timestamps
            ), "Updates should have monotonic timestamps"

    def test_status_recovery_after_store_failure(self):
        """Test status operations recover gracefully from store failures."""
        mock_store = Mock()

        # Simulate intermittent store failures
        call_count = 0

        def failing_get(key):
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError("Store temporarily unavailable")
            return "PENDING"

        mock_store.get.side_effect = failing_get

        # First calls should fail, subsequent should succeed
        with pytest.raises(ConnectionError):
            mark_status("test_id", "FILLED", mock_store)

        with pytest.raises(ConnectionError):
            mark_status("test_id", "FILLED", mock_store)

        # Third call should succeed
        try:
            mark_status("test_id", "FILLED", mock_store)
            mock_store.put.assert_called()
        except Exception as e:
            pytest.fail(f"Should recover after store failures: {e}")

    def test_bulk_status_updates_maintain_monotonicity(self):
        """Test bulk status updates maintain monotonicity constraints."""
        mock_store = Mock()

        # Setup bulk update scenario
        order_ids = [f"order_{i}" for i in range(5)]

        # All start in SUBMITTED state
        mock_store.get.return_value = "SUBMITTED"

        # Bulk update to PENDING should succeed
        for order_id in order_ids:
            try:
                mark_status(order_id, "PENDING", mock_store)
            except Exception as e:
                pytest.fail(f"Bulk update to PENDING should succeed: {e}")

        # Check all updates were called
        assert mock_store.put.call_count == len(order_ids), "Should update all orders"

        # Reset for next bulk update
        mock_store.reset_mock()
        mock_store.get.return_value = "PENDING"

        # Bulk update to FILLED should succeed
        for order_id in order_ids:
            try:
                mark_status(order_id, "FILLED", mock_store)
            except Exception as e:
                pytest.fail(f"Bulk update to FILLED should succeed: {e}")

        assert mock_store.put.call_count == len(
            order_ids
        ), "Should update all orders to FILLED"
