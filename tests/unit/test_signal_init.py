# tests/unit/test_signal_init.py
"""
Tests for core/signal/__init__.py
"""

import pytest
from core import signal
from core.signal import leadlag_hy, score, __all__


class TestSignalInit:
    """Test signal module initialization."""

    def test_submodules_imported(self):
        """Test that submodules are properly imported."""
        assert leadlag_hy is not None
        assert score is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = ["leadlag_hy", "score"]
        assert __all__ == expected

    def test_module_attributes(self):
        """Test that module has expected attributes."""
        assert hasattr(signal, 'leadlag_hy')
        assert hasattr(signal, 'score')