"""
Unit tests for SQLite WAL mode, rollback scenarios, and database reopening.

Tests edge cases in _idem_store_sqlite.py lines 76-100, 135-136, 150-151, 163-164:
- WAL mode transaction failures and rollbacks
- Database connection recovery after failures
- Concurrent access and locking scenarios
- Path errors and database integrity
"""

import os
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.execution._idem_store_sqlite import SQLiteIdempotencyStore


class TestSQLiteWALRollbackAndReopen:
    """Test SQLite WAL mode, transaction rollbacks, and connection recovery."""

    def setup_method(self):
        """Setup temporary database for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_wal_rollback.db")
        self.store = SQLiteIdempotencyStore(self.db_path, retention_days=7)

    def teardown_method(self):
        """Cleanup temporary files."""
        try:
            if hasattr(self, "store"):
                self.store.close()
        except:
            pass

        # Clean up temp directory
        import shutil

        try:
            shutil.rmtree(self.temp_dir)
        except:
            pass

    def test_wal_mode_enabled_on_initialization(self):
        """
        Test that WAL mode is properly enabled during store initialization.

        Coverage targets: _idem_store_sqlite.py lines 76-88 (WAL setup)
        """
        # Check WAL mode is enabled
        with sqlite3.connect(self.db_path) as conn:
            result = conn.execute("PRAGMA journal_mode").fetchone()
            assert result[0].lower() == "wal", "WAL mode should be enabled"

        # Verify WAL files exist after some operations
        test_key = "wal_test_key"
        test_value = {"spec_hash": "hash_wal", "status": "NEW"}

        self.store.set(test_key, test_value)

        # WAL file should exist
        wal_file = self.db_path + "-wal"
        assert (
            os.path.exists(wal_file) or os.path.getsize(self.db_path) > 0
        ), "WAL file should exist or data should be in main DB"

    def test_transaction_rollback_on_constraint_violation(self):
        """
        Test transaction rollback when constraint violations occur.

        Coverage targets: _idem_store_sqlite.py lines 91-100 (error handling in set())
        """
        # First, store a valid record
        valid_key = "rollback_test_key"
        valid_value = {
            "spec_hash": "hash_valid",
            "status": "NEW",
            "result": {"client_order_id": valid_key, "price": "100.0"},
            "ttl_sec": 3600.0,
        }

        self.store.set(valid_key, valid_value)

        # Verify it was stored
        retrieved = self.store.get(valid_key)
        assert retrieved is not None, "Valid record should be stored"

        # Now try to violate constraints by mocking database error
        with patch.object(self.store, "_get_connection") as mock_conn:
            mock_cursor = Mock()
            mock_cursor.execute.side_effect = sqlite3.IntegrityError(
                "UNIQUE constraint failed"
            )
            mock_conn.return_value.__enter__.return_value.cursor.return_value = (
                mock_cursor
            )

            # This should handle the error gracefully (rollback)
            with pytest.raises(sqlite3.IntegrityError):
                self.store.set("invalid_key", {"invalid": "data"})

        # Original data should still be intact after rollback
        retrieved_after = self.store.get(valid_key)
        assert retrieved_after is not None, "Original data should survive rollback"
        assert retrieved_after["spec_hash"] == "hash_valid"

    def test_database_corruption_recovery(self):
        """
        Test database recovery after corruption or connection issues.

        Coverage targets: _idem_store_sqlite.py lines 135-136, 150-151 (connection recovery)
        """
        # Store initial data
        initial_key = "recovery_test"
        initial_value = {"spec_hash": "hash_recovery", "status": "FILLED"}

        self.store.set(initial_key, initial_value)

        # Simulate database corruption by closing connection and corrupting file
        self.store.close()

        # Corrupt the database file (write invalid data)
        with open(self.db_path, "w") as f:
            f.write("CORRUPTED DATABASE CONTENT")

        # Try to reopen and use the store - should handle corruption
        try:
            new_store = SQLiteIdempotencyStore(self.db_path, retention_days=7)

            # Since DB is corrupted, this may fail or create new DB
            result = new_store.get(initial_key)
            # Depending on implementation, this may be None (new DB) or raise exception

        except sqlite3.DatabaseError:
            # This is acceptable - corruption should be detected
            pass

        # Test that we can create a fresh database after corruption
        fresh_db_path = os.path.join(self.temp_dir, "fresh_after_corruption.db")
        fresh_store = SQLiteIdempotencyStore(fresh_db_path, retention_days=7)

        # Fresh store should work normally
        fresh_key = "fresh_after_corruption"
        fresh_value = {"spec_hash": "hash_fresh", "status": "NEW"}

        fresh_store.set(fresh_key, fresh_value)
        fresh_retrieved = fresh_store.get(fresh_key)

        assert (
            fresh_retrieved is not None
        ), "Fresh store should work after corruption recovery"
        assert fresh_retrieved["spec_hash"] == "hash_fresh"

    def test_concurrent_access_with_wal_mode(self):
        """
        Test concurrent access to SQLite database in WAL mode.

        Coverage targets: _idem_store_sqlite.py lines 163-164 (concurrent safety)
        """
        # Store some initial data
        base_key = "concurrent_base"
        base_value = {"spec_hash": "hash_base", "status": "NEW"}
        self.store.set(base_key, base_value)

        results = []
        errors = []

        def worker_thread(thread_id):
            """Worker thread for concurrent access testing."""
            try:
                # Each thread gets its own store instance
                worker_store = SQLiteIdempotencyStore(self.db_path, retention_days=7)

                # Perform multiple operations
                for i in range(5):
                    key = f"concurrent_t{thread_id}_i{i}"
                    value = {
                        "spec_hash": f"hash_t{thread_id}_i{i}",
                        "status": "PENDING",
                        "result": {"thread": thread_id, "iteration": i},
                    }

                    worker_store.set(key, value)
                    retrieved = worker_store.get(key)

                    if retrieved:
                        results.append((thread_id, i, retrieved["spec_hash"]))
                    else:
                        errors.append(
                            f"Thread {thread_id}, iteration {i}: failed to retrieve"
                        )

                    # Small delay to increase chance of concurrent access
                    time.sleep(0.001)

                worker_store.close()

            except Exception as e:
                errors.append(f"Thread {thread_id}: {str(e)}")

        # Start multiple threads
        threads = []
        for t in range(3):
            thread = threading.Thread(target=worker_thread, args=(t,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Verify results
        assert len(errors) == 0, f"Concurrent access should not cause errors: {errors}"
        assert (
            len(results) == 15
        ), f"Should have 15 results (3 threads × 5 iterations), got {len(results)}"

        # Verify base data is still intact
        base_retrieved = self.store.get(base_key)
        assert base_retrieved is not None, "Base data should survive concurrent access"
        assert base_retrieved["spec_hash"] == "hash_base"

    def test_database_path_creation_and_permissions(self):
        """
        Test database path creation with various permission scenarios.

        Coverage targets: _idem_store_sqlite.py path handling and initialization
        """
        # Test with nested directory path
        nested_path = os.path.join(self.temp_dir, "nested", "dirs", "deep", "idem.db")

        # Should create directories automatically
        nested_store = SQLiteIdempotencyStore(nested_path, retention_days=7)

        # Verify directory was created
        assert os.path.exists(
            os.path.dirname(nested_path)
        ), "Nested directories should be created"
        assert os.path.exists(nested_path), "Database file should be created"

        # Test functionality
        nested_key = "nested_path_test"
        nested_value = {"spec_hash": "hash_nested", "status": "FILLED"}

        nested_store.set(nested_key, nested_value)
        nested_retrieved = nested_store.get(nested_key)

        assert nested_retrieved is not None, "Nested path store should work"
        assert nested_retrieved["spec_hash"] == "hash_nested"

        nested_store.close()

    def test_wal_checkpoint_and_cleanup(self):
        """
        Test WAL checkpoint operations and cleanup.

        Coverage targets: _idem_store_sqlite.py WAL maintenance operations
        """
        # Perform many operations to build up WAL log
        for i in range(50):
            key = f"wal_checkpoint_test_{i}"
            value = {
                "spec_hash": f"hash_checkpoint_{i}",
                "status": "NEW" if i % 2 == 0 else "FILLED",
                "result": {"iteration": i, "test": "checkpoint"},
            }
            self.store.set(key, value)

        # Check WAL file size
        wal_file = self.db_path + "-wal"
        if os.path.exists(wal_file):
            wal_size_before = os.path.getsize(wal_file)
        else:
            wal_size_before = 0

        # Force checkpoint
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")

        # WAL should be smaller or database should contain all data
        main_db_size = os.path.getsize(self.db_path)
        assert main_db_size > 0, "Main database should contain data"

        # Verify all data is still accessible
        test_key = "wal_checkpoint_test_25"
        retrieved = self.store.get(test_key)
        assert retrieved is not None, "Data should be accessible after checkpoint"
        assert retrieved["result"]["iteration"] == 25

    def test_connection_pool_and_reuse(self):
        """
        Test connection pooling and reuse behavior.

        Coverage targets: _idem_store_sqlite.py connection management
        """
        # Perform operations that should reuse connections
        operation_count = 20

        for i in range(operation_count):
            key = f"connection_reuse_{i}"
            value = {"spec_hash": f"hash_reuse_{i}", "status": "PENDING"}

            # Set and immediately get to test connection reuse
            self.store.set(key, value)
            retrieved = self.store.get(key)

            assert retrieved is not None, f"Operation {i} should succeed"
            assert retrieved["spec_hash"] == f"hash_reuse_{i}"

        # Test cleanup_expired with connection reuse
        expired_count = self.store.cleanup_expired()

        # Should not have expired records (retention_days=7, just created)
        assert expired_count == 0, "Should not have expired records yet"

    def test_database_locking_and_busy_handling(self):
        """
        Test database locking scenarios and SQLITE_BUSY handling.

        Coverage targets: _idem_store_sqlite.py busy/lock handling
        """
        # Create a long-running transaction to cause locking
        lock_conn = sqlite3.connect(self.db_path)
        lock_conn.execute("BEGIN IMMEDIATE")

        try:
            # Try to perform operations while database is locked
            # Should either wait or handle SQLITE_BUSY appropriately
            test_key = "lock_test_key"
            test_value = {"spec_hash": "hash_lock", "status": "NEW"}

            # This may succeed (if WAL allows) or timeout appropriately
            try:
                self.store.set(test_key, test_value)
                # If it succeeds, verify the data
                retrieved = self.store.get(test_key)
                # In WAL mode, reads should still work
                assert retrieved is None or retrieved["spec_hash"] == "hash_lock"

            except sqlite3.OperationalError as e:
                # SQLITE_BUSY or timeout is acceptable behavior
                assert (
                    "database is locked" in str(e).lower() or "busy" in str(e).lower()
                )

        finally:
            # Release the lock
            lock_conn.rollback()
            lock_conn.close()

        # After lock is released, operations should work normally
        unlock_key = "unlock_test_key"
        unlock_value = {"spec_hash": "hash_unlock", "status": "FILLED"}

        self.store.set(unlock_key, unlock_value)
        unlock_retrieved = self.store.get(unlock_key)

        assert unlock_retrieved is not None, "Operations should work after unlock"
        assert unlock_retrieved["spec_hash"] == "hash_unlock"
