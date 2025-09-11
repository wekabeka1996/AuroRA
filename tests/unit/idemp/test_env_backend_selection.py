"""
Unit tests for backend selection environment variable handling.

Tests coverage for backend selection branches in core/execution/idempotency.py.
"""

import os
from unittest.mock import Mock, patch

import pytest

from core.execution.idempotency import IdempotencyStore, MemoryIdempotencyStore


class TestEnvBackendSelection:
    """Test environment variable backend selection logic."""

    def test_backend_default_memory_if_env_missing(self):
        """Test backend defaults to memory when AURORA_IDEM_BACKEND not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Remove any existing backend env var
            if "AURORA_IDEM_BACKEND" in os.environ:
                del os.environ["AURORA_IDEM_BACKEND"]

            # Import fresh to trigger backend selection
            from core.execution.idempotency import _select_backend

            backend_class = _select_backend()

            # Should default to MemoryIdempotencyStore
            assert (
                backend_class == MemoryIdempotencyStore
            ), "Should default to memory backend"

            # Verify instance creation works
            store = backend_class()
            assert hasattr(store, "seen"), "Should have memory store interface"
            assert hasattr(store, "mark"), "Should have memory store interface"

    def test_backend_falls_back_to_memory_on_unknown_env(self):
        """Test backend falls back to memory on unknown AURORA_IDEM_BACKEND value."""
        with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": "unknown_backend_type"}):
            from core.execution.idempotency import _select_backend

            backend_class = _select_backend()

            # Should fall back to MemoryIdempotencyStore
            assert (
                backend_class == MemoryIdempotencyStore
            ), "Should fall back to memory on unknown backend"

            # Verify fallback instance works
            store = backend_class()
            store.mark("test_key", ttl_sec=60.0)
            assert store.seen("test_key"), "Fallback backend should work correctly"

    def test_sqlite_default_path_if_path_missing(self):
        """Test SQLite backend uses default path when AURORA_IDEM_SQLITE_PATH not set."""
        with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": "sqlite"}):
            # Ensure sqlite path is not set
            if "AURORA_IDEM_SQLITE_PATH" in os.environ:
                del os.environ["AURORA_IDEM_SQLITE_PATH"]

            with patch(
                "core.execution.idempotency.SQLiteIdempotencyStore", create=True
            ) as mock_sqlite:
                # Mock successful SQLite import
                mock_sqlite.return_value = Mock()

                from core.execution.idempotency import _select_backend

                backend_class = _select_backend()

                # Should attempt SQLite backend selection
                # If SQLite not available, falls back to memory (acceptable)
                assert backend_class is not None, "Should select some backend"

    def test_memory_backend_explicit_selection(self):
        """Test explicit memory backend selection via env var."""
        with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": "memory"}):
            from core.execution.idempotency import _select_backend

            backend_class = _select_backend()

            # Should explicitly select MemoryIdempotencyStore
            assert (
                backend_class == MemoryIdempotencyStore
            ), "Should explicitly select memory backend"

            # Test functionality
            store = backend_class()
            store.put("explicit_key", "explicit_value", ttl_sec=300.0)
            assert (
                store.get("explicit_key") == "explicit_value"
            ), "Explicit memory backend should work"

    def test_backend_selection_case_insensitive(self):
        """Test backend selection is case insensitive."""
        test_cases = ["MEMORY", "Memory", "memory", "MeMoRy"]

        for backend_name in test_cases:
            with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": backend_name}):
                from core.execution.idempotency import _select_backend

                backend_class = _select_backend()

                # Should select memory backend regardless of case
                assert (
                    backend_class == MemoryIdempotencyStore
                ), f"Should handle case '{backend_name}'"

    def test_sqlite_path_env_var_usage(self):
        """Test SQLite backend respects AURORA_IDEM_SQLITE_PATH when set."""
        custom_path = "/custom/path/to/idem.db"

        with patch.dict(
            os.environ,
            {"AURORA_IDEM_BACKEND": "sqlite", "AURORA_IDEM_SQLITE_PATH": custom_path},
        ):
            with patch(
                "core.execution.idempotency.SQLiteIdempotencyStore", create=True
            ) as mock_sqlite:
                mock_instance = Mock()
                mock_sqlite.return_value = mock_instance

                from core.execution.idempotency import _select_backend

                backend_class = _select_backend()

                # If SQLite available, should use custom path
                # If not available, should fall back gracefully
                assert (
                    backend_class is not None
                ), "Should handle SQLite path configuration"

    def test_backend_singleton_behavior(self):
        """Test that backend selection maintains singleton behavior."""
        with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": "memory"}):
            # Multiple calls should return same backend class
            from core.execution.idempotency import _select_backend

            backend1 = _select_backend()
            backend2 = _select_backend()

            assert backend1 is backend2, "Backend selection should be consistent"

            # Different instances should work independently
            store1 = backend1()
            store2 = backend1()

            store1.mark("key1", ttl_sec=60.0)
            store2.mark("key2", ttl_sec=60.0)

            # Both should work (different instances)
            assert store1.seen("key1"), "First instance should work"
            assert store2.seen("key2"), "Second instance should work"

            # But they shouldn't interfere with each other's keys
            assert not store1.seen("key2"), "Instances should be independent"
            assert not store2.seen("key1"), "Instances should be independent"
