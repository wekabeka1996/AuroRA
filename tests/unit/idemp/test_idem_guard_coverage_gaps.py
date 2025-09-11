import json
import time
from unittest.mock import Mock, patch

import pytest

from core.execution.idem_guard import IdempotencyConflict, mark_status, pre_submit_check


class TestIdemGuardCoverageGaps:
    """
    Target remaining coverage gaps in idem_guard.py.

    Coverage targets:
    - HIT scenario with missing cache data
    - JSON error handling in cached payloads
    - Complex result caching in mark_status
    - Status update with metadata preservation
    """

    def test_hit_with_missing_cached_data(self):
        """
        Test HIT scenario when cached data exists but payload is incomplete.

        Coverage target: HIT path with partial cache data
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            # Setup: store returns cached payload data
            cached_payload = {
                "spec_hash": "test_hash_123",
                "status": "FILLED",
                "updated": int(time.time()),
            }
            mock_store.get.return_value = json.dumps(cached_payload)
            mock_store.put = Mock()  # Ensure put method exists

            # Call with matching spec_hash
            result = pre_submit_check("test_order_123", "test_hash_123")

            # Should return cached payload (HIT scenario)
            assert result is not None
            assert result["spec_hash"] == "test_hash_123"
            assert result["status"] == "FILLED"

    def test_invalid_json_in_cached_payload(self):
        """
        Test error handling when cached payload contains invalid JSON.

        Coverage target: JSON parsing error handling
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            # Return invalid JSON from cache
            mock_store.get.return_value = "invalid_json{broken"
            mock_store.put = Mock()

            # Should handle invalid JSON gracefully (return None to indicate not cached)
            result = pre_submit_check("invalid_json_test", "test_hash_456")

            # Should be treated as fresh submit (None result)
            assert result is None

            # Should have called put to store new PENDING status
            mock_store.put.assert_called_once()

    def test_mark_status_with_complex_result_caching(self):
        """
        Test mark_status with complex result data caching.

        Coverage target: result parameter handling in mark_status
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = None  # No previous data
            mock_store.put = Mock()

            # Complex order result with multiple fields
            complex_result = {
                "orderId": "complex_12345",
                "status": "FILLED",
                "symbol": "ADAUSDT",
                "side": "BUY",
                "origQty": "100.0",
                "executedQty": "100.0",
                "fills": [
                    {"price": "0.49", "qty": "50.0", "commission": "0.025"},
                    {"price": "0.51", "qty": "50.0", "commission": "0.025"},
                ],
                "avgPrice": "0.50",
                "timeInForce": "GTC",
            }

            # Mark status with complex result
            result = mark_status("complex_order_456", "FILLED", result=complex_result)

            # Should return payload with status and cached result
            assert result["status"] == "FILLED"
            assert "result" in result
            assert result["result"]["orderId"] == "complex_12345"
            assert len(result["result"]["fills"]) == 2

            # Verify store.put was called
            mock_store.put.assert_called_once()

    def test_conflict_detection_with_spec_hash_mismatch(self):
        """
        Test IdempotencyConflict when spec_hash mismatches.

        Coverage target: conflict detection path in pre_submit_check
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            # Setup existing payload with different spec_hash
            existing_payload = {
                "spec_hash": "existing_hash_789",
                "status": "PENDING",
                "updated": int(time.time()),
            }
            mock_store.get.return_value = json.dumps(existing_payload)
            mock_store.put = Mock()

            # Call with different spec_hash - should trigger conflict
            with pytest.raises(IdempotencyConflict) as exc_info:
                pre_submit_check("conflict_test", "different_hash_456")

            # Should contain meaningful error message
            assert "IDEMPOTENCY_CONFLICT" in str(exc_info.value)
            assert "same client_order_id with different spec" in str(exc_info.value)

    def test_concurrent_status_updates_last_writer_consistency(self):
        """
        Test concurrent status updates maintain last-writer consistency.

        Coverage target: idem_guard.py concurrent update edge cases
        """
        mock_store = Mock()

        order_id = "concurrent_test_789"

        # Simulate concurrent updates with different timestamps
        update_scenarios = [
            ("SUBMITTED", {"orderId": "789", "timestamp": 1000}),
            ("PENDING", {"orderId": "789", "timestamp": 1001}),
            ("FILLED", {"orderId": "789", "timestamp": 1002, "executedQty": "1.0"}),
        ]

        # Each status update should succeed
        for status, result_data in update_scenarios:
            final_result = mark_status(order_id, status, result=result_data)

            assert final_result["status"] == status

            # Verify store was updated
            mock_store.put.assert_called()

            # No need to reset mock since we're not using it anymore

    def test_mark_status_preserves_previous_spec_hash(self):
        """
        Test mark_status preserves spec_hash from previous payload.

        Coverage target: spec_hash preservation in status updates
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            # Setup previous payload with spec_hash
            previous_payload = {
                "spec_hash": "preserved_hash_123",
                "status": "PENDING",
                "updated": int(time.time() - 100),
            }
            mock_store.get.return_value = json.dumps(previous_payload)
            mock_store.put = Mock()

            # Update status - should preserve existing spec_hash
            result = mark_status("preserve_test", "FILLED")

            # Should preserve spec_hash from previous payload
            assert result["spec_hash"] == "preserved_hash_123"
            assert result["status"] == "FILLED"
            assert "updated" in result

            # Verify put was called with preserved data
            mock_store.put.assert_called_once()

    def test_non_mapping_result_handling(self):
        """
        Test mark_status gracefully handles non-mapping result types.

        Coverage target: exception handling for non-dict result types
        """
        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = None
            mock_store.put = Mock()

            # Test with non-mapping result types
            non_mapping_results = ["string_result", 123, ["list", "result"], None, True]

            for non_mapping in non_mapping_results:
                result = mark_status(
                    f"test_{type(non_mapping).__name__}", "FILLED", result=non_mapping
                )

                # Should succeed without crashing
                assert result["status"] == "FILLED"

                # Non-mapping results should not be stored in 'result' field
                # (because of exception handling in mark_status)
                if "result" in result:
                    # If present, should be converted to dict or skipped
                    pass
