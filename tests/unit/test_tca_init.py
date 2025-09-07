# tests/unit/test_tca_init.py
"""
Tests for core/tca/__init__.py
"""

import pytest
from core.tca import (
    latency, hazard_cox, hawkes, TCAAnalyzer, TCAMetrics, FillEvent,
    OrderExecution, TCAInputs, TCAComponents, __all__
)


class TestTCAInit:
    """Test TCA module initialization."""

    def test_submodules_imported(self):
        """Test that submodules are properly imported."""
        assert latency is not None
        assert hazard_cox is not None
        assert hawkes is not None

    def test_classes_imported(self):
        """Test that classes are properly imported."""
        assert TCAAnalyzer is not None
        assert TCAMetrics is not None
        assert FillEvent is not None
        assert OrderExecution is not None
        assert TCAInputs is not None
        assert TCAComponents is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = [
            "latency", "hazard_cox", "hawkes",
            "TCAAnalyzer", "TCAMetrics", "FillEvent", "OrderExecution",
            "TCAInputs", "TCAComponents"
        ]
        assert __all__ == expected