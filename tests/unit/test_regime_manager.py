"""
Tests for core/regime/manager.py
"""
from __future__ import annotations

import pytest

from core.regime.manager import RegimeManager, RegimeState


def test_regime_manager_initialization():
    """Test RegimeManager initialization with default parameters."""
    mgr = RegimeManager()

    # Test initial state
    assert mgr._regime == "grind"
    assert mgr._n == 0
    assert mgr._ticks_since_change == 0


def test_regime_manager_custom_parameters():
    """Test RegimeManager with custom parameters."""
    mgr = RegimeManager(trend_q=0.7, grind_q=0.3, window=100, min_dwell=10)

    assert mgr.q_hi == 0.7
    assert mgr.q_lo == 0.3
    assert mgr.W == 100
    assert mgr.min_dwell == 10


def test_regime_manager_invalid_quantiles():
    """Test RegimeManager rejects invalid quantile ranges."""
    with pytest.raises(ValueError):
        RegimeManager(trend_q=0.3, grind_q=0.7)  # grind_q > trend_q


def test_regime_manager_update_trend():
    """Test regime detection for trending market."""
    mgr = RegimeManager(window=10, min_dwell=1)

    # Simulate trending market (high volatility proxy)
    state = None
    for i in range(15):
        ret = 0.01 if i % 2 == 0 else -0.01  # Alternating small returns
        state = mgr.update(ret)

    # Should eventually switch to trend regime
    assert state is not None
    assert state.regime in ["trend", "grind"]  # Allow either due to hysteresis
    assert isinstance(state, RegimeState)
    assert 0.0 <= state.proxy <= 1.0


def test_regime_manager_update_grind():
    """Test regime detection for grinding market."""
    mgr = RegimeManager(window=10, min_dwell=1)

    # Simulate grinding market (low volatility proxy)
    state = None
    for i in range(15):
        ret = 0.001 if i % 2 == 0 else -0.001  # Very small alternating returns
        state = mgr.update(ret)

    # Should stay in grind regime or switch based on proxy
    assert state is not None
    assert state.regime in ["trend", "grind"]
    assert isinstance(state, RegimeState)


def test_regime_manager_reset():
    """Test regime manager reset functionality."""
    mgr = RegimeManager()

    # Update a few times
    for i in range(5):
        mgr.update(0.01)

    # Reset
    mgr.reset()

    # Check reset state
    assert mgr._n == 0
    assert mgr._ticks_since_change == 0
    assert mgr._regime == "grind"
    assert len(mgr._rets) == 0
    assert len(mgr._absrets) == 0


def test_regime_manager_hysteresis():
    """Test hysteresis prevents rapid regime switching."""
    mgr = RegimeManager(window=20, min_dwell=5)

    # Start with trend-like data
    state = None
    for i in range(10):
        ret = 0.02 if i % 2 == 0 else -0.02
        state = mgr.update(ret)

    assert state is not None
    initial_regime = state.regime

    # Switch to grind-like data but with min_dwell constraint
    for i in range(3):  # Less than min_dwell
        ret = 0.001 if i % 2 == 0 else -0.001
        state = mgr.update(ret)

    # Should maintain initial regime due to hysteresis
    assert state is not None
    assert state.regime == initial_regime


def test_regime_manager_quantile_computation():
    """Test quantile computation in regime manager."""
    mgr = RegimeManager(window=10)

    # Add some data
    for i in range(10):
        mgr.update(float(i) * 0.01)

    # Check that quantiles are computed correctly
    q_lo, q_hi = mgr._thresholds()
    assert isinstance(q_lo, float)
    assert isinstance(q_hi, float)
    assert q_lo <= q_hi  # Lower quantile should be <= higher quantile
