"""
Unit tests for idempotency store basic functionality.

Simple unit tests targeting coverage gaps in core/execution/idempotency.py.
"""

import os
import tempfile
from unittest.mock import Mock, patch

import pytest

from core.execution.idempotency import IdempotencyStore, MemoryIdempotencyStore


class TestIdempotencyBasics:
    """Basic idempotency store functionality tests."""

    def setup_method(self):
        """Setup test environment."""
        self.memory_store = MemoryIdempotencyStore()

    def test_memory_store_basic_operations(self):
        """Test basic memory store operations."""
        # Test seen() with non-existent key
        assert not self.memory_store.seen(
            "non_existent"
        ), "Non-existent key should return False"

        # Test mark() and seen()
        self.memory_store.mark("test_key", ttl_sec=300.0)
        assert self.memory_store.seen("test_key"), "Marked key should return True"

        # Test put() and get()
        self.memory_store.put("value_key", "test_value", ttl_sec=300.0)
        assert (
            self.memory_store.get("value_key") == "test_value"
        ), "Should retrieve stored value"

    def test_memory_store_ttl_expiry(self):
        """Test TTL expiry functionality."""
        with patch("time.time") as mock_time:
            # Start at time 100
            mock_time.return_value = 100.0

            # Mark with 10 second TTL
            self.memory_store.mark("expiry_test", ttl_sec=10.0)
            assert self.memory_store.seen("expiry_test"), "Should be seen before expiry"

            # Advance time past expiry
            mock_time.return_value = 115.0  # 15 seconds later
            assert not self.memory_store.seen(
                "expiry_test"
            ), "Should be expired after TTL"

    def test_backend_selection_memory_default(self):
        """Test that memory backend is default when no env var set."""
        with patch.dict(os.environ, {}, clear=True):
            # Should default to memory
            store_class = type(IdempotencyStore())
            assert (
                "Memory" in store_class.__name__
            ), "Should default to MemoryIdempotencyStore"

    def test_backend_selection_with_env_var(self):
        """Test backend selection with environment variable."""
        with patch.dict(os.environ, {"AURORA_IDEM_BACKEND": "memory"}):
            store_class = type(IdempotencyStore())
            assert "Memory" in store_class.__name__, "Should select memory backend"
