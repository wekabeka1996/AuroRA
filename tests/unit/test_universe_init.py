# tests/unit/test_universe_init.py
"""
Tests for core/universe/__init__.py
"""

import pytest
from core.universe import (
    EmaSmoother, Hysteresis, HState, Ranked, SymbolMetrics, UniverseRanker, __all__
)


class TestUniverseInit:
    """Test universe module initialization."""

    def test_imports_available(self):
        """Test that all imports are available."""
        assert EmaSmoother is not None
        assert Hysteresis is not None
        assert HState is not None
        assert Ranked is not None
        assert SymbolMetrics is not None
        assert UniverseRanker is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = [
            "EmaSmoother",
            "Hysteresis",
            "HState",
            "Ranked",
            "SymbolMetrics",
            "UniverseRanker",
        ]
        assert __all__ == expected