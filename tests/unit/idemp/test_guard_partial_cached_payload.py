"""
Unit tests for guard partial cached payload scenarios.

Tests coverage for partial cached payload handling in core/execution/idem_guard.py.
"""

import json
from unittest.mock import Mock, patch

import pytest

from core.execution.idem_guard import IdempotencyConflict, mark_status, pre_submit_check


class TestGuardPartialCachedPayload:
    """Test guard behavior with partial cached payloads."""

    def test_guard_hit_with_partial_status_cached(self):
        """Test HIT scenario when only status is cached, no full payload."""
        mock_store = Mock()

        # Setup: Only status is cached, no full orderresult payload
        mock_store.seen.return_value = True
        mock_store.get.side_effect = lambda key: {
            "status_key": "FILLED",
            "payload_key": None,  # No full payload cached
        }.get(key.split(":")[-1])

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Should return HIT with partial status info
        result = pre_submit_check("test_id", request_data, mock_store)

        assert result["status"] == "HIT", "Should detect HIT with partial cache"
        assert "cached_status" in result, "Should include cached status info"
        assert result["cached_status"] == "FILLED", "Should return cached status"

    def test_guard_hit_with_partial_payload_no_status(self):
        """Test HIT scenario when payload exists but status is missing."""
        mock_store = Mock()

        # Setup: Full payload cached but no status
        mock_store.seen.return_value = True
        cached_payload = {
            "orderId": "12345",
            "status": "PARTIALLY_FILLED",
            "executedQty": "0.005",
        }
        mock_store.get.side_effect = lambda key: {
            "payload_key": json.dumps(cached_payload),
            "status_key": None,  # No explicit status cached
        }.get(key.split(":")[-1])

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Should return HIT with payload info
        result = pre_submit_check("test_id", request_data, mock_store)

        assert result["status"] == "HIT", "Should detect HIT with partial cache"
        assert "cached_payload" in result, "Should include cached payload"

        # Should parse cached payload
        parsed_payload = json.loads(result["cached_payload"])
        assert (
            parsed_payload["orderId"] == "12345"
        ), "Should parse cached payload correctly"

    def test_guard_cache_key_collision_different_specs(self):
        """Test behavior when cache key exists but for different order spec."""
        mock_store = Mock()

        # Setup: Key exists but for different order specification
        mock_store.seen.return_value = True

        # Cached data is for different order (different price)
        cached_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "49000.0",  # Different price
        }
        cached_spec_hash = hash(json.dumps(cached_spec, sort_keys=True))

        # Current request has different spec
        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",  # Different price
        }

        mock_store.get.side_effect = lambda key: {
            "spec_hash_key": str(cached_spec_hash),
            "payload_key": json.dumps({"orderId": "old_order"}),
            "status_key": "FILLED",
        }.get(key.split(":")[-1])

        # Should detect CONFLICT due to spec hash mismatch
        with pytest.raises(IdempotencyConflict) as exc_info:
            pre_submit_check("test_id", request_data, mock_store)

        assert "specification mismatch" in str(
            exc_info.value
        ), "Should detect spec mismatch"

    def test_guard_malformed_cached_payload_handling(self):
        """Test guard handles malformed cached payload gracefully."""
        mock_store = Mock()

        # Setup: Cached payload is malformed JSON
        mock_store.seen.return_value = True
        mock_store.get.side_effect = lambda key: {
            "payload_key": "invalid_json_payload{broken",  # Malformed JSON
            "status_key": "FILLED",
        }.get(key.split(":")[-1])

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Should handle malformed payload gracefully
        result = pre_submit_check("test_id", request_data, mock_store)

        # Should still return HIT with available status
        assert result["status"] == "HIT", "Should handle malformed payload gracefully"
        assert (
            result.get("cached_status") == "FILLED"
        ), "Should still return valid status"
        assert (
            "cached_payload" not in result or result["cached_payload"] is None
        ), "Should not return malformed payload"

    def test_guard_empty_cache_values_handling(self):
        """Test guard handles empty/None cache values correctly."""
        mock_store = Mock()

        # Setup: Cache key exists but values are empty/None
        mock_store.seen.return_value = True
        mock_store.get.side_effect = lambda key: {
            "payload_key": "",  # Empty string
            "status_key": None,  # None value
        }.get(key.split(":")[-1])

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Should handle empty values gracefully
        result = pre_submit_check("test_id", request_data, mock_store)

        # Should return appropriate response for empty cache
        if result["status"] == "HIT":
            # If treated as HIT, should handle empty values
            assert result.get("cached_payload") in [
                None,
                "",
            ], "Should handle empty payload"
            assert result.get("cached_status") is None, "Should handle None status"
        else:
            # Or should be treated as MISS due to empty cache
            assert result["status"] == "MISS", "Should handle empty cache as MISS"

    def test_mark_status_with_partial_update(self):
        """Test mark_status updates only status without overriding existing payload."""
        mock_store = Mock()

        # Setup: Existing payload in cache
        existing_payload = json.dumps({"orderId": "12345", "executedQty": "0.005"})
        mock_store.get.return_value = existing_payload

        # Mark new status
        mark_status("test_id", "FILLED", mock_store)

        # Should update status but preserve existing payload
        mock_store.put.assert_called()

        # Check that put was called for status update
        put_calls = mock_store.put.call_args_list
        status_call = next((call for call in put_calls if "status" in str(call)), None)
        assert status_call is not None, "Should update status in cache"

    def test_cache_key_generation_consistency(self):
        """Test that cache key generation is consistent for same inputs."""
        from core.execution.idem_guard import _generate_cache_key

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Multiple calls should generate same key
        key1 = _generate_cache_key("test_id", request_data)
        key2 = _generate_cache_key("test_id", request_data)

        assert key1 == key2, "Cache key generation should be consistent"

        # Different order should generate different key
        different_request = request_data.copy()
        different_request["price"] = "51000.0"

        key3 = _generate_cache_key("test_id", different_request)
        assert key1 != key3, "Different requests should generate different keys"

    def test_guard_concurrent_partial_updates(self):
        """Test guard handles concurrent partial updates safely."""
        import threading
        import time

        mock_store = Mock()

        # Setup concurrent access simulation
        call_count = 0
        original_get = mock_store.get

        def slow_get(key):
            nonlocal call_count
            call_count += 1
            time.sleep(0.01)  # Simulate slow cache access
            return "PENDING" if "status" in key else None

        mock_store.get.side_effect = slow_get
        mock_store.seen.return_value = True

        request_data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        results = []
        exceptions = []

        def worker():
            try:
                result = pre_submit_check(
                    f"test_id_{threading.current_thread().ident}",
                    request_data,
                    mock_store,
                )
                results.append(result)
            except Exception as e:
                exceptions.append(e)

        # Start multiple concurrent workers
        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Should handle concurrent access without errors
        assert (
            len(exceptions) == 0
        ), f"Should handle concurrent access safely: {exceptions}"
        assert len(results) == 3, "All workers should complete successfully"

        # All should get consistent results
        statuses = [r["status"] for r in results]
        assert all(s == "HIT" for s in statuses), "All concurrent calls should get HIT"
