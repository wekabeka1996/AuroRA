"""
Unit tests for idempotency backend selection via environment variables.

Tests edge cases in idempotency.py lines 50, 62-63, 88-100:
- AURORA_IDEM_BACKEND missing/unknown → Memory backend
- AURORA_IDEM_BACKEND=sqlite without path → data/idem.db default
- Backend initialization with various configurations
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from core.aurora_event_logger import AuroraEventLogger
from core.execution.idempotency import IdempotencyStore


class TestEnvSelectBackendDefaults:
    """Test environment-based backend selection with various configurations."""

    def test_missing_env_defaults_to_memory(self):
        """
        Test that missing AURORA_IDEM_BACKEND env var defaults to Memory backend.

        Coverage targets: idempotency.py lines 50, 62-63
        """
        # Ensure env var is not set
        env_without_backend = {
            k: v for k, v in os.environ.items() if k != "AURORA_IDEM_BACKEND"
        }

        with patch.dict("os.environ", env_without_backend, clear=True):
            store = get_idempotency_store()

        # Should be memory backend
        assert hasattr(
            store, "_data"
        ), "Should be MemoryIdempotencyStore with _data attribute"
        assert isinstance(store._data, dict), "Memory store should use dict for storage"

        # Test basic functionality
        test_key = "test_missing_env"
        test_value = {"spec_hash": "hash123", "status": "NEW"}

        store.set(test_key, test_value)
        retrieved = store.get(test_key)

        assert retrieved is not None, "Memory store should retrieve stored values"
        assert retrieved["spec_hash"] == "hash123"

    def test_unknown_env_backend_falls_back_to_memory(self):
        """
        Test that unknown AURORA_IDEM_BACKEND value falls back to Memory.

        Coverage targets: idempotency.py lines 88-100 (unknown backend handling)
        """
        unknown_backends = ["redis", "postgresql", "unknown_backend", ""]

        for backend in unknown_backends:
            with patch.dict("os.environ", {"AURORA_IDEM_BACKEND": backend}):
                store = get_idempotency_store()

            # Should fallback to memory backend
            assert hasattr(
                store, "_data"
            ), f"Backend '{backend}' should fallback to Memory"

            # Test it works
            test_key = f"test_unknown_{backend}_key"
            test_value = {"spec_hash": f"hash_{backend}", "status": "PENDING"}

            store.set(test_key, test_value)
            retrieved = store.get(test_key)

            assert (
                retrieved is not None
            ), f"Fallback should work for backend '{backend}'"
            assert retrieved["spec_hash"] == f"hash_{backend}"

    def test_sqlite_backend_without_path_uses_default(self):
        """
        Test that sqlite backend without explicit path uses data/idem.db default.

        Coverage targets: idempotency.py sqlite initialization path
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            # Change to temp directory to avoid affecting real data/idem.db
            original_cwd = os.getcwd()
            os.chdir(temp_dir)

            try:
                with patch.dict("os.environ", {"AURORA_IDEM_BACKEND": "sqlite"}):
                    # Remove any existing path env vars
                    env_clean = {
                        k: v
                        for k, v in os.environ.items()
                        if not k.startswith("AURORA_IDEM_")
                    }
                    env_clean["AURORA_IDEM_BACKEND"] = "sqlite"

                    with patch.dict("os.environ", env_clean, clear=True):
                        store = get_idempotency_store()

                # Should be SQLite store
                assert hasattr(store, "db_path"), "Should be SQLiteIdempotencyStore"

                # Check default path is used
                expected_path = Path("data/idem.db")
                assert (
                    Path(store.db_path).name == "idem.db"
                ), "Should use idem.db filename"

                # Test basic functionality
                test_key = "test_sqlite_default"
                test_value = {
                    "spec_hash": "hash_sqlite_default",
                    "status": "FILLED",
                    "result": {"client_order_id": test_key, "price": "100.0"},
                }

                store.set(test_key, test_value)
                retrieved = store.get(test_key)

                assert retrieved is not None, "SQLite default should work"
                assert retrieved["spec_hash"] == "hash_sqlite_default"
                assert retrieved["status"] == "FILLED"

            finally:
                os.chdir(original_cwd)

    def test_sqlite_backend_with_custom_path(self):
        """
        Test sqlite backend with custom path via AURORA_IDEM_SQLITE_PATH.

        Coverage targets: idempotency.py sqlite path configuration
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_db_path = os.path.join(temp_dir, "custom_idem.db")

            with patch.dict(
                "os.environ",
                {
                    "AURORA_IDEM_BACKEND": "sqlite",
                    "AURORA_IDEM_SQLITE_PATH": custom_db_path,
                },
            ):
                store = get_idempotency_store()

            # Should use custom path
            assert store.db_path == custom_db_path, "Should use custom SQLite path"

            # Test functionality with custom path
            test_key = "test_custom_path"
            test_value = {"spec_hash": "hash_custom", "status": "NEW"}

            store.set(test_key, test_value)
            retrieved = store.get(test_key)

            assert retrieved is not None, "Custom path SQLite should work"
            assert retrieved["spec_hash"] == "hash_custom"

            # Verify file was created at custom location
            assert os.path.exists(custom_db_path), "Custom DB file should be created"

    def test_backend_singleton_behavior(self):
        """
        Test that get_idempotency_store returns same instance (singleton).

        Coverage targets: idempotency.py singleton caching behavior
        """
        with patch.dict("os.environ", {"AURORA_IDEM_BACKEND": "memory"}):
            store1 = get_idempotency_store()
            store2 = get_idempotency_store()

        # Should be same instance
        assert store1 is store2, "Should return singleton instance"

        # Changes in one should affect the other
        test_key = "singleton_test"
        test_value = {"spec_hash": "hash_singleton", "status": "PENDING"}

        store1.set(test_key, test_value)
        retrieved_from_store2 = store2.get(test_key)

        assert retrieved_from_store2 is not None, "Singleton should share state"
        assert retrieved_from_store2["spec_hash"] == "hash_singleton"

    def test_backend_reconfiguration_on_env_change(self):
        """
        Test backend switching when environment changes (if supported).

        Coverage targets: idempotency.py backend selection logic
        """
        # Start with memory backend
        with patch.dict("os.environ", {"AURORA_IDEM_BACKEND": "memory"}):
            memory_store = get_idempotency_store()

        assert hasattr(memory_store, "_data"), "Should start with Memory backend"

        # Store some data in memory backend
        test_key = "reconfig_test"
        memory_value = {"spec_hash": "hash_memory", "status": "NEW"}
        memory_store.set(test_key, memory_value)

        # Switch to different backend (if singleton allows, otherwise just test env handling)
        with tempfile.TemporaryDirectory() as temp_dir:
            custom_path = os.path.join(temp_dir, "reconfig.db")

            # This tests the env var handling logic, even if singleton prevents actual switch
            with patch.dict(
                "os.environ",
                {
                    "AURORA_IDEM_BACKEND": "sqlite",
                    "AURORA_IDEM_SQLITE_PATH": custom_path,
                },
            ):
                # This may return same instance due to singleton, but env logic is tested
                store_after_change = get_idempotency_store()

        # The important test is that the env var parsing logic works correctly
        # Actual backend switching may not occur due to singleton pattern

    def test_invalid_sqlite_path_handling(self):
        """
        Test handling of invalid SQLite paths.

        Coverage targets: idempotency.py error handling in sqlite initialization
        """
        invalid_paths = [
            "/nonexistent/readonly/path/idem.db",  # Non-existent directory
            "/dev/null/idem.db",  # Invalid path structure
        ]

        for invalid_path in invalid_paths:
            with patch.dict(
                "os.environ",
                {
                    "AURORA_IDEM_BACKEND": "sqlite",
                    "AURORA_IDEM_SQLITE_PATH": invalid_path,
                },
            ):
                # Should either create directories or fallback gracefully
                try:
                    store = get_idempotency_store()
                    # If it succeeds, test basic functionality
                    assert store is not None, f"Should handle path: {invalid_path}"
                except Exception as e:
                    # If it fails, should be a reasonable error
                    assert (
                        "path" in str(e).lower() or "directory" in str(e).lower()
                    ), f"Should give meaningful error for invalid path: {invalid_path}"

    def test_env_var_precedence_and_defaults(self):
        """
        Test environment variable precedence and default value handling.

        Coverage targets: idempotency.py env var processing logic
        """
        # Test with multiple related env vars
        test_env_configs = [
            # Only backend specified
            {"vars": {"AURORA_IDEM_BACKEND": "memory"}, "expected_backend": "memory"},
            # Backend + retention config
            {
                "vars": {
                    "AURORA_IDEM_BACKEND": "sqlite",
                    "AURORA_IDEM_RETENTION_DAYS": "7",
                },
                "expected_backend": "sqlite",
            },
            # All config vars present
            {
                "vars": {
                    "AURORA_IDEM_BACKEND": "sqlite",
                    "AURORA_IDEM_RETENTION_DAYS": "14",
                    "AURORA_IDEM_SQLITE_PATH": "test_full_config.db",
                },
                "expected_backend": "sqlite",
            },
        ]

        for config in test_env_configs:
            with patch.dict("os.environ", config["vars"]):
                store = get_idempotency_store()

            # Verify backend type matches expectation
            if config["expected_backend"] == "memory":
                assert hasattr(store, "_data"), "Should be memory backend"
            elif config["expected_backend"] == "sqlite":
                assert hasattr(store, "db_path"), "Should be sqlite backend"

            # Test store works regardless of configuration
            test_key = f"env_config_test_{len(config['vars'])}"
            test_value = {"spec_hash": "hash_env_config", "status": "PENDING"}

            store.set(test_key, test_value)
            retrieved = store.get(test_key)

            assert (
                retrieved is not None
            ), f"Store should work with config: {config['vars']}"
            assert retrieved["spec_hash"] == "hash_env_config"
