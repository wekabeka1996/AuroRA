"""
Unit tests for SQLite backend resilience and error handling.

Tests coverage for SQLite-specific error scenarios in core/execution/_idem_store_sqlite.py.
"""

import os
import sqlite3
import tempfile
import threading
import time
from unittest.mock import MagicMock, Mock, patch

import pytest

# Try to import SQLite store - may not be available in all environments
try:
    from core.execution._idem_store_sqlite import SQLiteIdempotencyStore

    SQLITE_AVAILABLE = True
except ImportError:
    SQLITE_AVAILABLE = False
    SQLiteIdempotencyStore = None


@pytest.mark.skipif(
    not SQLITE_AVAILABLE, reason="SQLite idempotency store not available"
)
class TestSQLiteResilience:
    """Test SQLite backend resilience and error handling."""

    def setup_method(self):
        """Setup test database in temporary location."""
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.temp_dir, "test_idem.db")

    def teardown_method(self):
        """Cleanup test database."""
        if hasattr(self, "db_path") and os.path.exists(self.db_path):
            try:
                os.unlink(self.db_path)
            except:
                pass
        if hasattr(self, "temp_dir"):
            try:
                os.rmdir(self.temp_dir)
            except:
                pass

    def test_sqlite_wal_mode_rollback(self):
        """Test SQLite WAL mode transaction rollback scenarios."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Force WAL mode
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()

        # Test transaction rollback scenario
        store.mark("test_key", ttl_sec=60.0)
        assert store.seen("test_key"), "Key should be marked"

        # Simulate rollback by direct database manipulation
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("BEGIN TRANSACTION")
                conn.execute(
                    "DELETE FROM idempotency_store WHERE key = ?", ("test_key",)
                )
                # Don't commit - simulate rollback
                conn.rollback()
        except sqlite3.Error as e:
            # Expected in some rollback scenarios
            pass

        # Key should still exist after rollback
        assert store.seen("test_key"), "Key should survive rollback"

    def test_sqlite_concurrent_access_safety(self):
        """Test SQLite handles concurrent access safely."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        exceptions = []
        results = []

        def worker(worker_id):
            try:
                worker_store = SQLiteIdempotencyStore(db_path=self.db_path)
                key = f"concurrent_key_{worker_id}"

                worker_store.mark(key, ttl_sec=60.0)
                worker_store.put(key, f"data_{worker_id}", ttl_sec=60.0)

                # Verify data
                assert worker_store.seen(key), f"Worker {worker_id} key should be seen"
                data = worker_store.get(key)
                assert (
                    data == f"data_{worker_id}"
                ), f"Worker {worker_id} data should match"

                results.append(worker_id)

            except Exception as e:
                exceptions.append((worker_id, e))

        # Start multiple concurrent workers
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All workers should succeed
        assert len(exceptions) == 0, f"Concurrent access should be safe: {exceptions}"
        assert len(results) == 5, "All workers should complete successfully"

    def test_sqlite_corruption_recovery(self):
        """Test SQLite handles database corruption gracefully."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Add some data
        store.mark("test_key", ttl_sec=60.0)
        assert store.seen("test_key"), "Initial data should work"

        # Simulate corruption by writing invalid data to database file
        with open(self.db_path, "r+b") as f:
            f.seek(0)
            f.write(b"corrupted_database_content")
            f.flush()

        # Try to create new store instance - should handle corruption
        try:
            corrupted_store = SQLiteIdempotencyStore(db_path=self.db_path)
            # Should either recover or create new database
            corrupted_store.mark("recovery_key", ttl_sec=60.0)
            assert corrupted_store.seen(
                "recovery_key"
            ), "Should recover from corruption"
        except Exception as e:
            # Acceptable to fail gracefully on corruption
            assert "corrupt" in str(e).lower() or "database" in str(e).lower()

    def test_sqlite_disk_full_scenario(self):
        """Test SQLite handles disk full scenarios."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Mock disk full error
        original_execute = sqlite3.Connection.execute

        def mock_execute_disk_full(self, *args, **kwargs):
            if "INSERT" in str(args[0]).upper():
                raise sqlite3.OperationalError("database or disk is full")
            return original_execute(self, *args, **kwargs)

        with patch.object(sqlite3.Connection, "execute", mock_execute_disk_full):
            # Should handle disk full gracefully
            try:
                store.mark("disk_full_key", ttl_sec=60.0)
                pytest.fail("Should raise exception on disk full")
            except sqlite3.OperationalError as e:
                assert "disk is full" in str(e)

    def test_sqlite_connection_timeout_retry(self):
        """Test SQLite connection timeout and retry logic."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Lock database from another connection
        lock_conn = sqlite3.connect(self.db_path)
        lock_conn.execute("BEGIN EXCLUSIVE TRANSACTION")

        # Should handle locked database
        try:
            with pytest.raises(sqlite3.OperationalError):
                store.mark("locked_key", ttl_sec=60.0)
        finally:
            lock_conn.rollback()
            lock_conn.close()

        # After lock is released, should work
        store.mark("unlocked_key", ttl_sec=60.0)
        assert store.seen("unlocked_key"), "Should work after lock is released"

    def test_sqlite_schema_migration_robustness(self):
        """Test SQLite schema migration and compatibility."""
        # Create database with old schema
        with sqlite3.connect(self.db_path) as conn:
            # Simulate old schema without some columns
            conn.execute(
                """
                CREATE TABLE idempotency_store (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """
            )
            conn.execute(
                "INSERT INTO idempotency_store (key, value) VALUES (?, ?)",
                ("old_key", "old_value"),
            )
            conn.commit()

        # New store should handle schema migration
        try:
            store = SQLiteIdempotencyStore(db_path=self.db_path)
            # Should either migrate schema or work with existing data
            assert (
                store.get("old_key") == "old_value" or store.get("old_key") is None
            ), "Should handle schema migration"
        except Exception as e:
            # Acceptable to fail on incompatible schema
            assert "schema" in str(e).lower() or "table" in str(e).lower()

    def test_sqlite_cleanup_with_retention_policy(self):
        """Test SQLite cleanup respects retention policy."""
        # Test with very short retention for quick testing
        short_retention_days = 0.001  # ~1.5 minutes

        store = SQLiteIdempotencyStore(
            db_path=self.db_path, retention_days=short_retention_days
        )

        # Add data that should be cleaned up
        store.mark("cleanup_key", ttl_sec=0.1)  # Very short TTL
        assert store.seen("cleanup_key"), "Key should be initially present"

        # Wait for expiry
        time.sleep(0.2)

        # Trigger cleanup
        store.cleanup_expired()

        # Key should be cleaned up
        assert not store.seen("cleanup_key"), "Expired key should be cleaned up"

    def test_sqlite_vacuum_and_maintenance(self):
        """Test SQLite vacuum and maintenance operations."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Add and remove data to create fragmentation
        for i in range(100):
            store.mark(f"temp_key_{i}", ttl_sec=60.0)

        # Remove half the data
        for i in range(0, 100, 2):
            try:
                # Try to remove keys (if deletion method exists)
                with sqlite3.connect(self.db_path) as conn:
                    conn.execute(
                        "DELETE FROM idempotency_store WHERE key = ?",
                        (f"temp_key_{i}",),
                    )
                    conn.commit()
            except:
                pass

        # Test vacuum operation
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("VACUUM")
                conn.commit()
        except sqlite3.Error as e:
            # Vacuum might fail in some scenarios - that's acceptable
            pass

        # Database should still be functional after vacuum
        store.mark("post_vacuum_key", ttl_sec=60.0)
        assert store.seen("post_vacuum_key"), "Database should work after vacuum"

    def test_sqlite_wal_checkpoint_behavior(self):
        """Test SQLite WAL checkpoint behavior under load."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Force WAL mode
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.commit()

        # Generate many transactions to force WAL growth
        for i in range(50):
            store.mark(f"wal_key_{i}", ttl_sec=60.0)
            store.put(f"wal_key_{i}", f"data_{i}", ttl_sec=60.0)

        # Force checkpoint
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                conn.commit()
        except sqlite3.Error:
            # Checkpoint might fail - that's acceptable
            pass

        # Database should still be functional after checkpoint
        assert store.seen("wal_key_0"), "Database should work after WAL checkpoint"

    def test_sqlite_readonly_database_handling(self):
        """Test SQLite handles readonly database scenarios."""
        store = SQLiteIdempotencyStore(db_path=self.db_path)

        # Add initial data
        store.mark("readonly_test", ttl_sec=60.0)

        # Make database readonly
        os.chmod(self.db_path, 0o444)

        try:
            # New store instance should handle readonly database
            readonly_store = SQLiteIdempotencyStore(db_path=self.db_path)

            # Should be able to read
            assert readonly_store.seen(
                "readonly_test"
            ), "Should read from readonly database"

            # Write operations should fail gracefully
            with pytest.raises(sqlite3.OperationalError):
                readonly_store.mark("new_key", ttl_sec=60.0)

        finally:
            # Restore write permissions for cleanup
            os.chmod(self.db_path, 0o644)


# Fallback tests when SQLite is not available
@pytest.mark.skipif(
    SQLITE_AVAILABLE, reason="SQLite is available, no need for fallback tests"
)
class TestSQLiteFallback:
    """Test behavior when SQLite backend is not available."""

    def test_fallback_to_memory_when_sqlite_unavailable(self):
        """Test system falls back to memory store when SQLite is unavailable."""
        # This would test the import fallback logic
        # Implementation depends on how the system handles missing SQLite

        # Mock SQLite import failure
        with patch.dict("sys.modules", {"core.execution._idem_store_sqlite": None}):
            # Should fall back to memory store
            from core.execution.idempotency import (
                MemoryIdempotencyStore,
                _select_backend,
            )

            backend = _select_backend()
            assert (
                backend == MemoryIdempotencyStore
            ), "Should fall back to memory when SQLite unavailable"

    def test_graceful_degradation_without_sqlite(self):
        """Test graceful degradation when SQLite features are not available."""
        # Test that the system can operate without SQLite-specific features
        from core.execution.idempotency import MemoryIdempotencyStore

        # Memory store should provide basic functionality
        store = MemoryIdempotencyStore()

        store.mark("fallback_key", ttl_sec=60.0)
        assert store.seen("fallback_key"), "Memory fallback should work"

        store.put("fallback_key", "fallback_value", ttl_sec=60.0)
        assert (
            store.get("fallback_key") == "fallback_value"
        ), "Memory fallback should store data"
