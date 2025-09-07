# tests/unit/test_xai_init.py
"""
Tests for core/xai/__init__.py
"""

import pytest
from core.xai import (
    SCHEMA_ID, validate_decision, canonical_json, DecisionLogger,
    AlertResult, NoTradesAlert, DenySpikeAlert, CalibrationDriftAlert,
    CvarBreachAlert, __all__
)


class TestXAIInit:
    """Test XAI module initialization."""

    def test_functions_imported(self):
        """Test that functions are properly imported."""
        assert SCHEMA_ID is not None
        assert validate_decision is not None
        assert canonical_json is not None

    def test_classes_imported(self):
        """Test that classes are properly imported."""
        assert DecisionLogger is not None
        assert AlertResult is not None
        assert NoTradesAlert is not None
        assert DenySpikeAlert is not None
        assert CalibrationDriftAlert is not None
        assert CvarBreachAlert is not None

    def test_all_exports_defined(self):
        """Test that __all__ contains expected exports."""
        expected = [
            "SCHEMA_ID",
            "validate_decision",
            "canonical_json",
            "DecisionLogger",
            "AlertResult",
            "NoTradesAlert",
            "DenySpikeAlert",
            "CalibrationDriftAlert",
            "CvarBreachAlert",
        ]
        assert __all__ == expected