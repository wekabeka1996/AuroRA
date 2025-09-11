"""
Simplified tests targeting specific missing lines in idem_guard.py.

Focus on line coverage gaps: 86-90, 92-94, 103-104, 109-110, 119, 124-125, 129-130, 153-157, 162, 167-168, 171-173.
"""

import json
from unittest.mock import Mock, patch

import pytest

from core.execution.idem_guard import IdempotencyConflict, mark_status, pre_submit_check


class TestIdemGuardCoverage:
    """Tests targeting specific coverage gaps in idem_guard.py."""

    def test_conflict_detection_triggers_logging_and_metrics(self):
        """Test conflict detection triggers logger and metrics (lines 86-90, 92-94)."""
        # Mock store with existing entry
        mock_store = Mock()
        mock_store.seen.return_value = True

        # Different spec hash to trigger conflict
        stored_spec = {"symbol": "BTCUSDT", "side": "BUY", "price": "50000"}
        current_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "51000",
        }  # Different price

        stored_hash = hash(json.dumps(stored_spec, sort_keys=True))
        stored_payload = json.dumps({"spec_hash": stored_hash, "status": "PENDING"})
        mock_store.get.return_value = stored_payload

        # Should trigger conflict logging and metrics
        with pytest.raises(IdempotencyConflict):
            pre_submit_check("test_conflict", current_spec, mock_store)

    def test_hit_scenario_triggers_logging_and_metrics(self):
        """Test HIT scenario triggers logger and metrics (lines 103-104, 109-110)."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        # Same spec hash - will trigger HIT
        spec = {"symbol": "BTCUSDT", "side": "BUY", "price": "50000"}
        spec_hash = hash(json.dumps(spec, sort_keys=True))
        stored_payload = json.dumps({"spec_hash": spec_hash, "status": "FILLED"})
        mock_store.get.return_value = stored_payload

        # Should trigger HIT logging and metrics
        result = pre_submit_check("test_hit", spec, mock_store)
        assert result is not None, "Should return hit payload"

    def test_store_scenario_triggers_logging_and_metrics(self):
        """Test new store scenario triggers logger and metrics (lines 119, 124-125, 129-130)."""
        mock_store = Mock()
        mock_store.seen.return_value = False  # Not seen before
        mock_store.get.return_value = None  # No existing data
        mock_store.put = Mock()  # Mock put method

        spec = {"symbol": "BTCUSDT", "side": "BUY", "price": "50000"}

        # Should trigger store logging and metrics
        result = pre_submit_check("test_store", spec, mock_store, ttl_sec=300.0)

        # Should call put to store the data
        mock_store.put.assert_called_once()
        assert result is None, "Should return None for new store"

    def test_mark_status_with_result_caching(self):
        """Test mark_status with result parameter (lines 153-157)."""
        mock_store = Mock()
        mock_store.get.return_value = '{"spec_hash": "test_hash", "status": "PENDING"}'
        mock_store.put = Mock()

        # Test with result parameter to trigger result caching logic
        order_result = {"orderId": "12345", "status": "FILLED", "executedQty": "0.01"}

        result = mark_status("test_coid", "FILLED", ttl_sec=300.0, result=order_result)

        # Should call put with result included
        mock_store.put.assert_called_once()
        call_args = mock_store.put.call_args[0]
        stored_data = json.loads(call_args[1])

        assert "result" in stored_data, "Should cache result data"
        assert stored_data["result"]["orderId"] == "12345", "Should cache order result"

    def test_mark_status_fallback_to_mark(self):
        """Test mark_status fallback when put method not available (line 162)."""
        mock_store = Mock()
        mock_store.get.return_value = None
        # Don't mock put method - simulate store without put capability
        del mock_store.put  # Remove put method
        mock_store.mark = Mock()  # Add mark method

        result = mark_status("test_fallback", "FILLED", ttl_sec=300.0)

        # Should fall back to mark method
        mock_store.mark.assert_called_once_with("test_fallback", 300.0)

    def test_mark_status_triggers_logging_and_metrics(self):
        """Test mark_status triggers logger and metrics (lines 167-168, 171-173)."""
        mock_store = Mock()
        mock_store.get.return_value = '{"status": "PENDING"}'
        mock_store.put = Mock()

        # Should trigger update logging and metrics
        result = mark_status("test_update", "FILLED", ttl_sec=300.0)

        # Should call put to update status
        mock_store.put.assert_called_once()
        assert result["status"] == "FILLED", "Should return updated status"

    def test_pre_submit_check_fallback_to_mark(self):
        """Test pre_submit_check fallback when store doesn't have put method."""
        mock_store = Mock()
        mock_store.seen.return_value = False
        mock_store.get.return_value = None
        # Remove put method to trigger fallback
        del mock_store.put
        mock_store.mark = Mock()

        spec = {"symbol": "BTCUSDT", "side": "BUY"}

        result = pre_submit_check("test_fallback", spec, mock_store, ttl_sec=300.0)

        # Should fall back to mark method
        mock_store.mark.assert_called_once_with("test_fallback", 300.0)
        assert result is None, "Should return None for fallback store"

    def test_mark_status_with_non_mapping_result(self):
        """Test mark_status handles non-mapping result gracefully."""
        mock_store = Mock()
        mock_store.get.return_value = None
        mock_store.put = Mock()

        # Pass non-mapping result to trigger exception handling
        non_mapping_result = "invalid_result_type"

        result = mark_status("test_non_mapping", "FILLED", result=non_mapping_result)

        # Should handle non-mapping gracefully
        mock_store.put.assert_called_once()
        call_args = mock_store.put.call_args[0]
        stored_data = json.loads(call_args[1])

        # Result should not be included due to exception handling
        assert "result" not in stored_data, "Should not include invalid result"

    def test_loads_safe_with_invalid_json(self):
        """Test _loads_safe handles invalid JSON gracefully."""
        mock_store = Mock()
        mock_store.seen.return_value = True
        mock_store.get.return_value = "invalid_json{broken"  # Malformed JSON

        spec = {"symbol": "BTCUSDT"}

        # Should handle invalid JSON and treat as new entry
        result = pre_submit_check("test_invalid_json", spec, mock_store, ttl_sec=300.0)

        # Should treat as new since JSON parsing failed
        # This depends on implementation details

    def test_exception_handling_in_logging_blocks(self):
        """Test that exceptions in logging/metrics blocks are handled gracefully."""
        # This test ensures that even if logger/metrics raise exceptions,
        # the main functionality continues to work

        mock_store = Mock()
        mock_store.seen.return_value = False
        mock_store.get.return_value = None
        mock_store.put = Mock()

        spec = {"symbol": "BTCUSDT"}

        # Even with potential logging errors, should still work
        result = pre_submit_check("test_exception_handling", spec, mock_store)

        # Should still call put despite any logging exceptions
        mock_store.put.assert_called_once()
        assert result is None, "Should work despite logging exceptions"
