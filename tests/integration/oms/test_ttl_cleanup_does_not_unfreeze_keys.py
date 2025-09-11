"""
Test TTL cleanup behavior for SQLite idempotency store.

Key test: test_ttl_cleanup_does_not_unfreeze_keys
- Verify cleanup_expired() does not affect non-expired keys
- Verify get() never deletes records, only reports None for expired
- Verify AURORA_IDEM_RETENTION_DAYS controls retention window
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from core.execution._idem_store_sqlite import SQLiteIdempotencyStore


class MockTimeNs:
    """Mock time.time_ns() with manual control."""

    def __init__(self, initial_time_ns: int = None):
        self.current_time_ns = initial_time_ns or int(time.time() * 1e9)

    def __call__(self) -> int:
        return self.current_time_ns

    def advance_seconds(self, seconds: float):
        """Advance mock time by specified seconds."""
        self.current_time_ns += int(seconds * 1e9)

    def advance_days(self, days: int):
        """Advance mock time by specified days."""
        self.advance_seconds(days * 24 * 60 * 60)


class TestTTLCleanup:
    """Test TTL and cleanup behavior in SQLite idempotency store."""

    def setup_method(self):
        """Setup test with temporary database."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_ttl.db"
        self.mock_time = MockTimeNs()
        self.store = SQLiteIdempotencyStore(
            db_path=self.db_path, now_ns_fn=self.mock_time
        )

    def teardown_method(self):
        """Cleanup test database."""
        try:
            self.store.close()
            if self.db_path.exists():
                self.db_path.unlink()
            if Path(self.temp_dir).exists():
                import shutil

                shutil.rmtree(self.temp_dir)
        except Exception:
            pass

    def test_ttl_cleanup_does_not_unfreeze_keys(self):
        """
        Test that cleanup_expired() does not affect active (non-expired) keys.

        Scenario:
        1. Mark key with 10-minute TTL
        2. Advance time by 5 minutes (still valid)
        3. Run cleanup_expired()
        4. Verify key still seen() == True (not "unfrozen")
        5. Advance time by 6 more minutes (now expired)
        6. Verify seen() == False but record still exists
        7. Run cleanup with short retention window
        8. Verify record actually deleted
        """
        key = "test_ttl_key_001"

        # === STEP 1: Mark key with 10-minute TTL ===
        self.store.mark(key, ttl_sec=600.0)  # 10 minutes
        assert self.store.seen(key) is True, "Key should be seen immediately after mark"

        # === STEP 2: Advance time by 5 minutes (still valid) ===
        self.mock_time.advance_seconds(300.0)  # 5 minutes
        assert self.store.seen(key) is True, "Key should still be valid after 5 minutes"

        # === STEP 3: Run cleanup_expired() ===
        # Should not affect non-expired keys
        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 0, "Should not clean up non-expired keys"

        # === STEP 4: Verify key still seen() == True ===
        assert self.store.seen(key) is True, "Cleanup should not unfreeze active keys"

        # === STEP 5: Advance time by 6 more minutes (now expired) ===
        self.mock_time.advance_seconds(360.0)  # 6 more minutes = 11 minutes total
        assert self.store.seen(key) is False, "Key should be expired after 11 minutes"

        # === STEP 6: Verify record still exists (get() doesn't delete) ===
        # Check database directly to verify record exists
        assert self.store.size() == 1, "Record should still exist in database"

        # get() should return None for expired but not delete
        value = self.store.get(key)
        assert value is None, "get() should return None for expired key"
        assert self.store.size() == 1, "get() should not delete expired records"

        # === STEP 7: Run cleanup with default retention (30 days) ===
        # Should not clean up yet (only 11 minutes old)
        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 0, "Should not clean up records within retention window"
        assert (
            self.store.size() == 1
        ), "Record should still exist within retention window"

        # === STEP 8: Advance time beyond retention and cleanup ===
        self.mock_time.advance_days(31)  # Advance 31 days
        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 1, "Should clean up records beyond retention window"
        assert (
            self.store.size() == 0
        ), "Record should be deleted after retention cleanup"

    def test_get_never_deletes_expired_records(self):
        """Test that get() never deletes expired records, only returns None."""
        key = "test_no_delete_key"
        value = "test_value"

        # Store key-value with 1-second TTL
        self.store.put(key, value, ttl_sec=1.0)
        assert self.store.get(key) == value, "Should get value before expiry"

        # Advance time past expiry
        self.mock_time.advance_seconds(2.0)

        # Multiple get() calls should not delete the record
        for i in range(5):
            result = self.store.get(key)
            assert (
                result is None
            ), f"get() call {i+1} should return None for expired key"
            assert (
                self.store.size() == 1
            ), f"get() call {i+1} should not delete expired record"

    def test_seen_never_deletes_expired_records(self):
        """Test that seen() never deletes expired records, only returns False."""
        key = "test_seen_no_delete"

        # Mark key with 1-second TTL
        self.store.mark(key, ttl_sec=1.0)
        assert self.store.seen(key) is True, "Should be seen before expiry"

        # Advance time past expiry
        self.mock_time.advance_seconds(2.0)

        # Multiple seen() calls should not delete the record
        for i in range(5):
            result = self.store.seen(key)
            assert (
                result is False
            ), f"seen() call {i+1} should return False for expired key"
            assert (
                self.store.size() == 1
            ), f"seen() call {i+1} should not delete expired record"

    def test_cleanup_respects_retention_days_env(self):
        """Test that cleanup_expired() respects AURORA_IDEM_RETENTION_DAYS."""
        key = "test_retention_env"

        # Mark key with 1-second TTL
        self.store.mark(key, ttl_sec=1.0)

        # Advance time past TTL expiry
        self.mock_time.advance_seconds(2.0)
        assert self.store.seen(key) is False, "Key should be expired"

        # Test with custom retention period (1 day)
        with patch.dict(os.environ, {"AURORA_IDEM_RETENTION_DAYS": "1"}):
            # Advance time by 12 hours (within 1-day retention)
            self.mock_time.advance_seconds(12 * 60 * 60)

            cleaned_count = self.store.cleanup_expired()
            assert cleaned_count == 0, "Should not clean within 1-day retention window"
            assert self.store.size() == 1, "Record should still exist"

            # Advance time by 2 more days (beyond 1-day retention)
            self.mock_time.advance_days(2)

            cleaned_count = self.store.cleanup_expired()
            assert cleaned_count == 1, "Should clean after 1-day retention window"
            assert self.store.size() == 0, "Record should be deleted"

    def test_cleanup_handles_invalid_retention_env(self):
        """Test that cleanup_expired() handles invalid AURORA_IDEM_RETENTION_DAYS gracefully."""
        key = "test_invalid_retention"

        # Mark key with 1-second TTL
        self.store.mark(key, ttl_sec=1.0)
        self.mock_time.advance_seconds(2.0)  # Expire the key

        # Test with invalid retention environment variable
        with patch.dict(os.environ, {"AURORA_IDEM_RETENTION_DAYS": "invalid"}):
            # Should default to 30 days
            self.mock_time.advance_days(31)  # Beyond 30-day default

            cleaned_count = self.store.cleanup_expired()
            assert cleaned_count == 1, "Should use 30-day default for invalid env var"

    def test_cleanup_multiple_expired_records(self):
        """Test cleanup_expired() with multiple records at different expiry times."""
        keys_and_ttls = [
            ("key_1sec", 1.0),  # Expires after 1 second
            ("key_5sec", 5.0),  # Expires after 5 seconds
            ("key_10sec", 10.0),  # Expires after 10 seconds
        ]

        # Mark all keys
        for key, ttl in keys_and_ttls:
            self.store.mark(key, ttl_sec=ttl)

        assert self.store.size() == 3, "Should have 3 records"

        # Advance time by 3 seconds (only key_1sec expired)
        self.mock_time.advance_seconds(3.0)

        # Cleanup should not remove anything (within retention window)
        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 0, "Should not clean records within retention window"
        assert self.store.size() == 3, "All records should still exist"

        # Advance time by 31 days to exceed retention
        self.mock_time.advance_days(31)

        # Now cleanup should remove the expired record
        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 1, "Should clean 1 expired record beyond retention"
        assert self.store.size() == 2, "Should have 2 records remaining"

        # Advance more time to expire remaining keys and exceed retention
        self.mock_time.advance_seconds(10.0)  # Expire remaining keys
        self.mock_time.advance_days(31)  # Exceed retention for them too

        cleaned_count = self.store.cleanup_expired()
        assert cleaned_count == 2, "Should clean remaining 2 expired records"
        assert self.store.size() == 0, "Should have no records remaining"

    def test_mark_updates_expiry_without_cleanup(self):
        """Test that mark() can update expiry time without triggering cleanup."""
        key = "test_mark_update"

        # Initial mark with 2-second TTL
        self.store.mark(key, ttl_sec=2.0)

        # Advance time by 1 second (still valid)
        self.mock_time.advance_seconds(1.0)
        assert self.store.seen(key) is True, "Key should still be valid"

        # Re-mark with extended TTL
        self.store.mark(key, ttl_sec=10.0)  # Extend to 10 seconds from now

        # Advance time by 2 more seconds (would have been expired with original TTL)
        self.mock_time.advance_seconds(2.0)
        assert self.store.seen(key) is True, "Key should be valid with extended TTL"

        # Verify no cleanup occurred during mark operations
        assert self.store.size() == 1, "Should still have 1 record"

    def test_concurrent_cleanup_safety(self):
        """Test that cleanup_expired() is safe with concurrent operations."""
        import threading
        import time as real_time

        key_base = "concurrent_test"
        results = []

        def mark_and_check():
            """Mark a key and verify it's seen."""
            thread_id = threading.current_thread().ident
            key = f"{key_base}_{thread_id}"

            try:
                self.store.mark(key, ttl_sec=1.0)
                seen_before = self.store.seen(key)
                results.append(("mark", thread_id, seen_before))
            except Exception as e:
                results.append(("error", thread_id, str(e)))

        def cleanup_expired():
            """Run cleanup_expired()."""
            try:
                count = self.store.cleanup_expired()
                results.append(("cleanup", threading.current_thread().ident, count))
            except Exception as e:
                results.append(
                    ("cleanup_error", threading.current_thread().ident, str(e))
                )

        # Start multiple threads doing mark operations
        threads = []
        for i in range(3):
            t = threading.Thread(target=mark_and_check)
            threads.append(t)
            t.start()

        # Start cleanup thread
        cleanup_thread = threading.Thread(target=cleanup_expired)
        threads.append(cleanup_thread)
        cleanup_thread.start()

        # Wait for all threads
        for t in threads:
            t.join(timeout=5.0)

        # Verify no exceptions occurred
        errors = [r for r in results if r[0] in ("error", "cleanup_error")]
        assert len(errors) == 0, f"Should have no errors, but got: {errors}"

        # Verify mark operations succeeded
        mark_results = [r for r in results if r[0] == "mark"]
        assert len(mark_results) == 3, "Should have 3 successful mark operations"

        for op, thread_id, seen in mark_results:
            assert seen is True, f"Thread {thread_id} should have seen its key"
