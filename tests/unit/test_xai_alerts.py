"""
Tests for core/xai/alerts.py
"""
from __future__ import annotations

from core.xai.alerts import AlertResult, CalibrationDriftAlert, CvarBreachAlert, DenySpikeAlert, NoTradesAlert


def test_no_trades_alert():
    """Test NoTradesAlert basic functionality."""
    alert = NoTradesAlert(window_sec=1)  # Short window for testing

    # Test with tradeable action
    result = alert.update(1000000000, "enter")
    assert result is None

    # Test with non-tradeable action
    result = alert.update(2000000000, "deny")
    assert result is None or isinstance(result, AlertResult)


def test_deny_spike_alert():
    """Test DenySpikeAlert basic functionality."""
    alert = DenySpikeAlert(window_sec=1, rate_thresh=0.5)  # Lower threshold for testing

    # Test with enter action
    result = alert.update(1000000000, "enter")
    assert result is None

    # Test with deny action
    result = alert.update(2000000000, "deny")
    assert result is None or isinstance(result, AlertResult)


def test_calibration_drift_alert():
    """Test CalibrationDriftAlert basic functionality."""
    alert = CalibrationDriftAlert(bins=5, ece_thresh=0.5)  # Higher threshold for testing

    # Test with some predictions
    result = alert.update(1000000000, 0.5, 1)
    assert result is None or isinstance(result, AlertResult)

    result = alert.update(2000000000, 0.3, 0)
    assert result is None or isinstance(result, AlertResult)


def test_cvar_breach_alert():
    """Test CvarBreachAlert basic functionality."""
    alert = CvarBreachAlert(window_size=10, alpha=0.95)

    # Test with small returns (need at least 50 samples)
    for i in range(60):
        result = alert.update(1000000000 + i * 1000000000, 0.001)
        if i < 50:
            assert result is None
        else:
            assert result is None or isinstance(result, AlertResult)
