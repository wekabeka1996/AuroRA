# tests/unit/test_logging_init.py
"""
Tests for core/logging/__init__.py
"""

import pytest
from core.logging import AntiFloodLogger, AntiFloodJSONLWriter, create_default_anti_flood_logger, __all__


class TestLoggingInit:
    """Test logging module initialization."""

    def test_imports_available(self):
        """Test that all imports are available."""
        assert AntiFloodLogger is not None
        assert AntiFloodJSONLWriter is not None
        assert create_default_anti_flood_logger is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = ['AntiFloodLogger', 'AntiFloodJSONLWriter', 'create_default_anti_flood_logger']
        assert __all__ == expected

    def test_create_default_anti_flood_logger_function(self):
        """Test that create_default_anti_flood_logger is callable."""
        assert callable(create_default_anti_flood_logger)