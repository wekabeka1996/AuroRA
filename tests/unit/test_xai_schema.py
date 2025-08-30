"""
Tests for core/xai/schema.py
"""
from __future__ import annotations

import pytest
from core.xai.schema import validate_decision


def test_validate_decision_valid():
    """Test validation of a valid decision record."""
    valid_decision = {
        "decision_id": "test-123",
        "timestamp_ns": 1000000000,
        "symbol": "BTCUSDT",
        "action": "enter",
        "score": 0.8,
        "p_raw": 0.7,
        "p": 0.65,
        "threshold": 0.6,
        "features": {"test": 1.0},
        "components": {"test": 0.5},
        "config_hash": "abc123",
        "config_schema_version": "1.0",
        "model_version": "test-1.0",
    }

    # Should not raise an exception
    validate_decision(valid_decision)


def test_validate_decision_missing_required():
    """Test validation fails with missing required fields."""
    invalid_decision = {
        "decision_id": "test-123",
        # Missing timestamp_ns
        "symbol": "BTCUSDT",
        "action": "enter",
    }

    with pytest.raises(ValueError):
        validate_decision(invalid_decision)


def test_validate_decision_invalid_action():
    """Test validation fails with invalid action type."""
    invalid_decision = {
        "decision_id": "test-123",
        "timestamp_ns": 1000000000,
        "symbol": "BTCUSDT",
        "action": 123,  # Invalid type - should be str
        "score": 0.8,
        "p_raw": 0.7,
        "p": 0.65,
        "threshold": 0.6,
        "features": {"test": 1.0},
        "components": {"test": 0.5},
        "config_hash": "abc123",
        "config_schema_version": "1.0",
        "model_version": "test-1.0",
    }

    with pytest.raises(TypeError):
        validate_decision(invalid_decision)


def test_validate_decision_probability_bounds():
    """Test validation of probability bounds."""
    # Test p_raw out of bounds
    invalid_decision = {
        "decision_id": "test-123",
        "timestamp_ns": 1000000000,
        "symbol": "BTCUSDT",
        "action": "enter",
        "score": 0.8,
        "p_raw": 1.5,  # Invalid: > 1.0
        "p": 0.65,
        "threshold": 0.6,
        "features": {"test": 1.0},
        "components": {"test": 0.5},
        "config_hash": "abc123",
        "config_schema_version": "1.0",
        "model_version": "test-1.0",
    }

    with pytest.raises(ValueError):
        validate_decision(invalid_decision)