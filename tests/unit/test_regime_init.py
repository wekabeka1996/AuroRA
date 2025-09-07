# tests/unit/test_regime_init.py
"""
Tests for core/regime/__init__.py
"""

import pytest
from core.regime import (
    PageHinkley, PHResult, GLRMeanShift, GLRResult, RegimeManager, RegimeState, __all__
)


class TestRegimeInit:
    """Test regime module initialization."""

    def test_imports_available(self):
        """Test that all imports are available."""
        assert PageHinkley is not None
        assert PHResult is not None
        assert GLRMeanShift is not None
        assert GLRResult is not None
        assert RegimeManager is not None
        assert RegimeState is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = [
            "PageHinkley",
            "PHResult",
            "GLRMeanShift",
            "GLRResult",
            "RegimeManager",
            "RegimeState",
        ]
        assert __all__ == expected