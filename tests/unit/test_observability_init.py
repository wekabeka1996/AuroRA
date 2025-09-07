# tests/unit/test_observability_init.py
"""
Tests for core/observability/__init__.py
"""

from core.observability import __version__, __all__


class TestObservabilityInit:
    """Test observability module initialization."""

    def test_version_defined(self):
        """Test that version is properly defined."""
        assert __version__ == "1.0.0"

    def test_all_exports_defined(self):
        """Test that __all__ is properly defined."""
        assert __all__ == ["metrics_bridge"]