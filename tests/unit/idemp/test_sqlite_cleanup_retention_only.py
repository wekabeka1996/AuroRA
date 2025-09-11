"""
Unit tests for SQLite cleanup_expired behavior and retention policy.

Tests that cleanup_expired() never affects get() operations and retention boundaries.
Coverage targets: _idem_store_sqlite.py cleanup logic isolation.
"""

import os
import tempfile
import time
from datetime import datetime, timedelta
from unittest.mock import Mock, patch

import pytest

from core.execution._idem_store_sqlite import SQLiteIdempotencyStore


class MockTimeNs:
    """Mock time.time_ns() for controlled time testing."""

    def __init__(self, initial_time_ns: int):
        self.current_time_ns = initial_time_ns

    def __call__(self) -> int:
        return self.current_time_ns

    def advance_seconds(self, seconds: float):
        """Advance mock time by specified seconds."""
        self.current_time_ns += int(seconds * 1_000_000_000)

    def advance_days(self, days: int):
        """Advance mock time by specified days."""
        self.advance_seconds(days * 24 * 3600)


class TestSQLiteCleanupRetentionOnly:
    """Test SQLite cleanup_expired isolation from get() operations."""

    def setup_method(self):
        """Setup temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_cleanup_retention.db")
        self.store = SQLiteIdempotencyStore(self.db_path, retention_days=7)

        # Setup mock time starting at a known point
        self.base_time_ns = int(
            datetime(2025, 9, 11, 10, 0, 0).timestamp() * 1_000_000_000
        )
        self.mock_time = MockTimeNs(self.base_time_ns)

    def teardown_method(self):
        """Cleanup temporary files."""
        try:
            if hasattr(self, "store"):
                self.store.close()
        except:
            pass

        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_cleanup_expired_does_not_affect_get_operations(self):
        """
        Test that cleanup_expired() never interferes with get() operations.

        Key principle: get() should NEVER delete records, only cleanup_expired() should.
        """
        with patch("time.time_ns", self.mock_time):
            # Store records at different times
            records = [
                {"key": "fresh_record", "age_days": 0, "should_survive": True},
                {"key": "week_old_record", "age_days": 6, "should_survive": True},
                {"key": "exactly_retention", "age_days": 7, "should_survive": False},
                {"key": "old_record", "age_days": 10, "should_survive": False},
                {"key": "very_old_record", "age_days": 30, "should_survive": False},
            ]

            # Store all records at their respective "ages"
            for record in records:
                # Set time to when record was "created"
                creation_time = self.base_time_ns - int(
                    record["age_days"] * 24 * 3600 * 1_000_000_000
                )
                self.mock_time.current_time_ns = creation_time

                value = {
                    "spec_hash": f"hash_{record['key']}",
                    "status": "FILLED",
                    "result": {"age_days": record["age_days"]},
                    "ttl_sec": 3600.0,
                }
                self.store.set(record["key"], value)

            # Reset time to "now"
            self.mock_time.current_time_ns = self.base_time_ns

            # CRITICAL TEST: get() operations should NOT trigger cleanup
            for record in records:
                retrieved = self.store.get(record["key"])

                # All records should be retrievable via get() regardless of age
                assert (
                    retrieved is not None
                ), f"get() should retrieve {record['key']} regardless of age"
                assert retrieved["spec_hash"] == f"hash_{record['key']}"
                assert retrieved["result"]["age_days"] == record["age_days"]

            # Now explicitly call cleanup_expired()
            expired_count = self.store.cleanup_expired()

            # Should have cleaned up exactly the expired records
            expected_expired = len([r for r in records if not r["should_survive"]])
            assert (
                expired_count == expected_expired
            ), f"Should expire {expected_expired} records"

            # After cleanup, get() should reflect the cleanup results
            for record in records:
                retrieved_after = self.store.get(record["key"])

                if record["should_survive"]:
                    assert (
                        retrieved_after is not None
                    ), f"{record['key']} should survive cleanup"
                    assert retrieved_after["spec_hash"] == f"hash_{record['key']}"
                else:
                    assert (
                        retrieved_after is None
                    ), f"{record['key']} should be cleaned up"

    def test_multiple_get_calls_never_trigger_cleanup(self):
        """
        Test that repeated get() calls never trigger cleanup operations.
        """
        with patch("time.time_ns", self.mock_time):
            # Store an old record that would be eligible for cleanup
            old_key = "old_but_accessible"
            self.mock_time.advance_days(-10)  # 10 days ago

            old_value = {
                "spec_hash": "hash_old_accessible",
                "status": "FILLED",
                "result": {"should_be_cleaned": True},
                "ttl_sec": 3600.0,
            }
            self.store.set(old_key, old_value)

            # Reset to current time
            self.mock_time.current_time_ns = self.base_time_ns

            # Call get() many times - should never trigger cleanup
            for i in range(100):
                retrieved = self.store.get(old_key)
                assert (
                    retrieved is not None
                ), f"get() call {i} should retrieve old record"
                assert retrieved["spec_hash"] == "hash_old_accessible"

            # Record should still exist after 100 get() calls
            final_retrieved = self.store.get(old_key)
            assert final_retrieved is not None, "Record should survive all get() calls"

            # Only explicit cleanup should remove it
            expired_count = self.store.cleanup_expired()
            assert expired_count == 1, "Should expire the old record"

            # Now get() should return None
            after_cleanup = self.store.get(old_key)
            assert after_cleanup is None, "Record should be gone after explicit cleanup"

    def test_cleanup_respects_exact_retention_boundary(self):
        """
        Test that cleanup_expired respects exact retention day boundaries.
        """
        with patch("time.time_ns", self.mock_time):
            retention_days = 7
            boundary_records = [
                {"key": "just_within", "hours_old": 7 * 24 - 1, "should_survive": True},
                {
                    "key": "exactly_boundary",
                    "hours_old": 7 * 24,
                    "should_survive": False,
                },
                {"key": "just_over", "hours_old": 7 * 24 + 1, "should_survive": False},
            ]

            # Store records at precise boundary times
            for record in boundary_records:
                creation_time_ns = self.base_time_ns - int(
                    record["hours_old"] * 3600 * 1_000_000_000
                )
                self.mock_time.current_time_ns = creation_time_ns

                value = {
                    "spec_hash": f"hash_{record['key']}",
                    "status": "NEW",
                    "result": {"hours_old": record["hours_old"]},
                    "ttl_sec": 3600.0,
                }
                self.store.set(record["key"], value)

            # Reset to current time
            self.mock_time.current_time_ns = self.base_time_ns

            # All should be accessible via get()
            for record in boundary_records:
                retrieved = self.store.get(record["key"])
                assert (
                    retrieved is not None
                ), f"get() should access {record['key']} at boundary"

            # Cleanup should respect exact boundaries
            expired_count = self.store.cleanup_expired()
            expected_expired = len(
                [r for r in boundary_records if not r["should_survive"]]
            )
            assert (
                expired_count == expected_expired
            ), "Should respect exact retention boundary"

            # Verify boundary behavior
            for record in boundary_records:
                retrieved_after = self.store.get(record["key"])

                if record["should_survive"]:
                    assert (
                        retrieved_after is not None
                    ), f"{record['key']} should survive boundary test"
                else:
                    assert (
                        retrieved_after is None
                    ), f"{record['key']} should be expired at boundary"

    def test_cleanup_with_concurrent_get_operations(self):
        """
        Test cleanup behavior when concurrent get() operations are happening.
        """
        import threading

        with patch("time.time_ns", self.mock_time):
            # Store mix of old and new records
            test_records = []
            for i in range(20):
                key = f"concurrent_test_{i}"
                age_days = 2 if i < 10 else 10  # Half new, half old

                creation_time = self.base_time_ns - int(
                    age_days * 24 * 3600 * 1_000_000_000
                )
                self.mock_time.current_time_ns = creation_time

                value = {
                    "spec_hash": f"hash_concurrent_{i}",
                    "status": "FILLED",
                    "result": {"index": i, "age_days": age_days},
                    "ttl_sec": 3600.0,
                }
                self.store.set(key, value)
                test_records.append({"key": key, "age_days": age_days, "index": i})

            # Reset to current time
            self.mock_time.current_time_ns = self.base_time_ns

            get_results = []
            cleanup_results = []

            def continuous_get_operations():
                """Continuously perform get() operations."""
                for _ in range(50):
                    for record in test_records[:10]:  # Only access "new" records
                        result = self.store.get(record["key"])
                        get_results.append(result is not None)
                    time.sleep(0.001)  # Small delay

            def cleanup_operation():
                """Perform cleanup operation."""
                expired = self.store.cleanup_expired()
                cleanup_results.append(expired)

            # Start concurrent operations
            get_thread = threading.Thread(target=continuous_get_operations)
            cleanup_thread = threading.Thread(target=cleanup_operation)

            get_thread.start()
            time.sleep(0.01)  # Let get operations start
            cleanup_thread.start()

            # Wait for completion
            get_thread.join(timeout=5.0)
            cleanup_thread.join(timeout=5.0)

            # Verify results
            assert len(cleanup_results) == 1, "Should have one cleanup result"
            assert cleanup_results[0] == 10, "Should clean up 10 old records"

            # All get() operations on new records should have succeeded
            successful_gets = sum(get_results)
            assert (
                successful_gets > 0
            ), "Some get() operations should succeed during cleanup"

            # Verify final state
            for record in test_records:
                final_state = self.store.get(record["key"])
                if record["age_days"] <= 7:
                    assert (
                        final_state is not None
                    ), f"New record {record['key']} should survive"
                else:
                    assert (
                        final_state is None
                    ), f"Old record {record['key']} should be cleaned"

    def test_empty_database_cleanup_behavior(self):
        """
        Test cleanup_expired behavior on empty database.
        """
        with patch("time.time_ns", self.mock_time):
            # Fresh database - no records
            expired_count = self.store.cleanup_expired()
            assert expired_count == 0, "Empty database should report 0 expired records"

            # get() on non-existent key should return None
            non_existent = self.store.get("does_not_exist")
            assert non_existent is None, "Non-existent key should return None"

            # Multiple cleanup calls should be safe
            for i in range(5):
                expired = self.store.cleanup_expired()
                assert (
                    expired == 0
                ), f"Cleanup call {i} should report 0 expired on empty DB"

    def test_cleanup_does_not_unfreeze_keys_principle(self):
        """
        Test the core principle: cleanup never "unfreezes" or affects active keys.

        This is the most critical test - cleanup should NEVER interfere with get().
        """
        with patch("time.time_ns", self.mock_time):
            # Create scenario where key would be eligible for cleanup
            active_key = "active_but_old"

            # Store record 15 days ago (way past retention)
            self.mock_time.advance_days(-15)
            old_value = {
                "spec_hash": "hash_active_old",
                "status": "FILLED",
                "result": {"critical_data": "must_preserve_during_get"},
                "ttl_sec": 3600.0,
            }
            self.store.set(active_key, old_value)

            # Reset to current time
            self.mock_time.current_time_ns = self.base_time_ns

            # CRITICAL: get() should return the record WITHOUT side effects
            retrieved_before_cleanup = self.store.get(active_key)
            assert (
                retrieved_before_cleanup is not None
            ), "get() should retrieve old record"
            assert retrieved_before_cleanup["spec_hash"] == "hash_active_old"

            # Record should still exist after get() (no unfreezing/cleanup)
            retrieved_again = self.store.get(active_key)
            assert (
                retrieved_again is not None
            ), "get() should not unfreeze/cleanup record"
            assert (
                retrieved_again["result"]["critical_data"] == "must_preserve_during_get"
            )

            # Only explicit cleanup should remove old records
            expired_count = self.store.cleanup_expired()
            assert expired_count == 1, "Explicit cleanup should remove old record"

            # After explicit cleanup, get() should return None
            retrieved_after_cleanup = self.store.get(active_key)
            assert (
                retrieved_after_cleanup is None
            ), "Record should be gone after explicit cleanup"

            # This demonstrates the principle:
            # - get() operations NEVER cause deletion
            # - Only explicit cleanup_expired() causes deletion
            # - cleanup_expired() and get() are completely isolated operations
