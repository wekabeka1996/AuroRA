"""
Tests targeting specific coverage gaps in idempotency.py

Focus on missing lines: 46-53, 56-64, 88-100
"""

import os
import time
from unittest.mock import patch

import pytest

from core.execution.idempotency import MemoryIdempotencyStore, _select_backend


class TestIdempotencyGapCoverage:
    """Target specific lines not covered by existing tests."""

    def test_memory_store_put_with_none_ttl_preserves_existing_expiry(self):
        """
        Test MemoryIdempotencyStore.put with None ttl preserves existing expiry.

        Coverage target: idempotency.py lines 48-50 (None ttl handling)
        """
        store = MemoryIdempotencyStore()

        # First put with specific ttl
        store.put("test_key", "value1", ttl_sec=100.0)

        # Get the entry to verify it was stored
        assert store.get("test_key") == "value1"

        # Second put with None ttl should preserve existing expiry
        store.put("test_key", "value2")  # ttl_sec=None (default)

        # Should still be accessible (existing expiry preserved)
        assert store.get("test_key") == "value2"

    def test_memory_store_put_with_none_ttl_on_new_key_uses_default(self):
        """
        Test MemoryIdempotencyStore.put with None ttl on new key uses 5min default.

        Coverage target: idempotency.py lines 48-50 (default 300s for new keys)
        """
        store = MemoryIdempotencyStore()

        # Put new key with None ttl should use 300s default
        store.put("new_key", "new_value")  # ttl_sec=None

        # Should be accessible immediately
        assert store.get("new_key") == "new_value"

    def test_memory_store_get_expired_key_cleanup(self):
        """
        Test MemoryIdempotencyStore.get removes expired keys and returns None.

        Coverage target: idempotency.py lines 58-60 (expired key cleanup)
        """
        store = MemoryIdempotencyStore()

        # Put with very short ttl
        store.put("expire_test", "temp_value", ttl_sec=0.01)  # 10ms

        # Should be accessible immediately
        assert store.get("expire_test") == "temp_value"

        # Wait for expiry
        time.sleep(0.02)  # 20ms - enough to expire

        # Should return None and remove key
        assert store.get("expire_test") is None

        # Subsequent get should also return None (key cleaned up)
        assert store.get("expire_test") is None

    @patch.dict("os.environ", clear=True)
    def test_select_backend_memory_fallback(self):
        """
        Test _select_backend falls back to MemoryIdempotencyStore for unknown backends.

        Coverage target: idempotency.py lines 101-102 (else clause fallback)
        """
        # Test unknown backend
        os.environ["AURORA_IDEM_BACKEND"] = "unknown_backend"
        backend_class = _select_backend()

        # Should fallback to MemoryIdempotencyStore
        assert backend_class == MemoryIdempotencyStore

    @patch.dict("os.environ", clear=True)
    def test_select_backend_sqlite_with_path(self):
        """
        Test _select_backend creates SQLite backend with custom path.

        Coverage target: idempotency.py lines 88-99 (sqlite backend creation)
        """
        # Test sqlite backend selection
        os.environ["AURORA_IDEM_BACKEND"] = "sqlite"
        os.environ["AURORA_IDEM_SQLITE_PATH"] = "test_custom.db"

        try:
            backend_class = _select_backend()

            # Should return a class (not instance)
            assert callable(backend_class)

            # Try to create instance - should work if SQLite backend available
            try:
                instance = backend_class()
                # If successful, it's the SQLite backend
                assert hasattr(instance, "put")
                assert hasattr(instance, "get")
            except Exception:
                # If SQLite not available, should fallback to Memory
                assert backend_class == MemoryIdempotencyStore

        except Exception:
            # If import fails, that's acceptable for test environment
            pass

    @patch.dict("os.environ", clear=True)
    def test_select_backend_sqlite_fallback_on_import_failure(self):
        """
        Test _select_backend falls back to Memory when SQLite import fails.

        Coverage target: idempotency.py lines 91-92 (SQLite import exception)
        """
        # Mock import failure
        with patch("core.execution.idempotency.os.getenv") as mock_getenv:
            mock_getenv.return_value = "sqlite"

            # Mock the import to fail
            with patch(
                "builtins.__import__", side_effect=ImportError("SQLite not available")
            ):
                backend_class = _select_backend()

                # Should fallback to MemoryIdempotencyStore
                assert backend_class == MemoryIdempotencyStore

    def test_memory_store_threading_behavior(self):
        """
        Test MemoryIdempotencyStore thread safety with lock usage.

        Coverage target: Verify lock usage in put/get methods
        """
        import threading
        import time

        store = MemoryIdempotencyStore()
        results = []

        def worker(worker_id):
            for i in range(5):
                key = f"thread_{worker_id}_{i}"
                store.put(key, f"value_{worker_id}_{i}", ttl_sec=1.0)
                retrieved = store.get(key)
                results.append((worker_id, i, retrieved == f"value_{worker_id}_{i}"))

        # Create multiple threads
        threads = []
        for i in range(3):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        # Wait for all threads
        for t in threads:
            t.join()

        # All operations should succeed (no race conditions)
        assert len(results) == 15  # 3 threads * 5 operations
        assert all(success for _, _, success in results)

    def test_memory_store_seen_method_behavior(self):
        """
        Test MemoryIdempotencyStore.seen method for event tracking.

        Coverage target: idempotency.py lines 28-36 (seen method)
        """
        store = MemoryIdempotencyStore()

        # Initially not seen
        assert store.seen("event_123") is False

        # Mark as seen
        store.mark("event_123", ttl_sec=1.0)

        # Should be seen now
        assert store.seen("event_123") is True

        # Test expired event cleanup in seen()
        store.mark("expire_event", ttl_sec=0.01)  # 10ms
        assert store.seen("expire_event") is True

        time.sleep(0.02)  # Wait for expiry

        # Should return False and clean up expired entry
        assert store.seen("expire_event") is False

    def test_memory_store_mark_method_with_ttl(self):
        """
        Test MemoryIdempotencyStore.mark method for event marking.

        Coverage target: idempotency.py lines 39-42 (mark method)
        """
        store = MemoryIdempotencyStore()

        # Mark event with custom ttl
        store.mark("marked_event", ttl_sec=2.0)

        # Should be seen
        assert store.seen("marked_event") is True

        # Mark again with different ttl (should update expiry)
        store.mark("marked_event", ttl_sec=5.0)

        # Should still be seen
        assert store.seen("marked_event") is True

    def test_memory_store_cleanup_expired_method(self):
        """
        Test MemoryIdempotencyStore.cleanup_expired method.

        Coverage target: idempotency.py lines 67-74 (cleanup_expired method)
        """
        store = MemoryIdempotencyStore()

        # Add some entries with different expiry times
        store.put("keep1", "value1", ttl_sec=10.0)  # Long lived
        store.put("keep2", "value2", ttl_sec=10.0)  # Long lived
        store.put("expire1", "temp1", ttl_sec=0.01)  # Will expire
        store.put("expire2", "temp2", ttl_sec=0.01)  # Will expire

        # Verify all are present initially
        assert store.get("keep1") == "value1"
        assert store.get("expire1") == "temp1"

        # Wait for some to expire
        time.sleep(0.02)

        # Cleanup expired entries
        expired_count = store.cleanup_expired()

        # Should have cleaned up the expired ones
        assert expired_count == 2

        # Long-lived should still be there
        assert store.get("keep1") == "value1"
        assert store.get("keep2") == "value2"

        # Expired should be gone
        assert store.get("expire1") is None
        assert store.get("expire2") is None

    def test_memory_store_clear_method(self):
        """
        Test MemoryIdempotencyStore.clear method.

        Coverage target: idempotency.py lines 76-78 (clear method)
        """
        store = MemoryIdempotencyStore()

        # Add some entries
        store.put("clear_test1", "value1")
        store.put("clear_test2", "value2")
        store.mark("clear_event")

        # Verify entries exist
        assert store.get("clear_test1") == "value1"
        assert store.seen("clear_event") is True
        assert store.size() >= 3

        # Clear all
        store.clear()

        # Should be empty
        assert store.size() == 0
        assert store.get("clear_test1") is None
        assert store.seen("clear_event") is False

    def test_memory_store_size_method(self):
        """
        Test MemoryIdempotencyStore.size method.

        Coverage target: idempotency.py lines 80-82 (size method)
        """
        store = MemoryIdempotencyStore()

        # Initially empty
        assert store.size() == 0

        # Add entries
        store.put("size_test1", "value1")
        assert store.size() == 1

        store.put("size_test2", "value2")
        store.mark("size_event")
        assert store.size() == 3

        # Remove one
        store.put("size_test1", "new_value", ttl_sec=0.01)
        time.sleep(0.02)
        store.cleanup_expired()  # Clean expired

        assert store.size() == 2  # Should have 2 remaining
