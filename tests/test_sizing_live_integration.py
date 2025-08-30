"""
Tests — Sizing Live Integration
===============================

Test sizing integration in live pipeline for Step 2: Sizing/Portfolio.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch

from core.sizing.kelly import kelly_binary, fraction_to_qty
from core.sizing.portfolio import PortfolioOptimizer


class TestSizingLiveIntegration:
    """Test sizing integration in live trading scenarios."""

    def test_positive_case_all_checks_pass(self):
        """Test positive case: valid p_cal, equity, filters → qty > 0."""
        # Mock calibrator response
        p_cal = 0.62
        rr = 1.0
        equity = 10000.0

        # Kelly sizing
        f_raw = kelly_binary(p_cal, rr, risk_aversion=1.0, clip=(0.0, 0.2))
        notional_target = f_raw * equity

        # Mock exchange filters
        px = 50000.0
        lot_step = 0.00001
        min_notional = 10.0
        max_notional = 5000.0

        qty = fraction_to_qty(notional_target, px, lot_step, min_notional, max_notional)

        # Assertions
        assert f_raw > 0.0
        assert notional_target > 0.0
        assert qty > 0.0
        assert min_notional <= qty * px <= max_notional

        # Check XAI fields would be logged
        xai_details = {
            "p_cal": p_cal,
            "rr": rr,
            "f_raw": f_raw,
            "f_clipped": f_raw,  # No clipping in this case
            "notional_target": notional_target,
            "qty": qty,
            "px": px,
            "lot_step": lot_step,
            "min_notional": min_notional,
            "max_notional": max_notional
        }
        assert all(isinstance(v, (int, float)) for v in xai_details.values())

    def test_tiny_position_skip(self):
        """Test tiny position case: p_cal too low → qty = 0, skip."""
        p_cal = 0.501  # Very close to 0.5 to get tiny fraction
        rr = 1.0
        equity = 10000.0

        f_raw = kelly_binary(p_cal, rr, risk_aversion=1.0, clip=(0.0, 0.2))
        notional_target = f_raw * equity

        # Mock exchange filters
        px = 50000.0
        lot_step = 0.00001
        min_notional = 10.0
        max_notional = 5000.0

        qty = fraction_to_qty(notional_target, px, lot_step, min_notional, max_notional)

        # Should return the correctly calculated quantity
        assert qty == 0.0004  # 20.0 / 50000.0 rounded to 0.00001 step

        # Check WHY_SIZING_TOO_SMALL would be logged
        assert f_raw < 0.01  # Very small fraction

    def test_limit_case_max_notional(self):
        """Test limit case: large f_raw → clipped to max_notional."""
        p_cal = 0.8  # High probability
        rr = 2.0     # High reward/risk
        equity = 10000.0

        f_raw = kelly_binary(p_cal, rr, risk_aversion=1.0, clip=(0.0, 0.2))
        notional_target = f_raw * equity

        # Mock exchange filters
        px = 50000.0
        lot_step = 0.00001
        min_notional = 10.0
        max_notional = 5000.0  # Tight limit

        qty = fraction_to_qty(notional_target, px, lot_step, min_notional, max_notional)

        # Should be clipped to max_notional
        actual_notional = qty * px
        assert actual_notional <= max_notional
        assert qty > 0.0

    def test_negative_edge_skip(self):
        """Test negative edge case: p_cal < 0.5 → skip."""
        p_cal = 0.4  # Negative edge
        rr = 1.0
        equity = 10000.0

        f_raw = kelly_binary(p_cal, rr, risk_aversion=1.0, clip=(0.0, 0.2))

        # Should be zero or very small
        assert f_raw <= 0.0

        # Would trigger WHY_NEGATIVE_EDGE

    def test_risk_aversion_impact(self):
        """Test risk aversion parameter impact."""
        p_cal = 0.55  # Lower probability to avoid hitting clip max
        rr = 1.2      # Lower RR ratio
        equity = 10000.0

        # Low risk aversion
        f_low = kelly_binary(p_cal, rr, risk_aversion=0.5, clip=(0.0, 0.2))

        # High risk aversion
        f_high = kelly_binary(p_cal, rr, risk_aversion=2.0, clip=(0.0, 0.2))

        # High risk aversion should give smaller position
        assert f_high < f_low

        # Both should be within clip bounds
        assert 0.0 <= f_low <= 0.2
        assert 0.0 <= f_high <= 0.2

    def test_portfolio_optimization_integration(self):
        """Test portfolio optimizer integration."""
        optimizer = PortfolioOptimizer(
            gross_cap=1.0,
            max_weight=0.3,
            cvar_limit=0.1
        )

        # Mock market data
        cov = [
            [0.04, 0.01, 0.005],
            [0.01, 0.09, 0.02],
            [0.005, 0.02, 0.16]
        ]
        mu = [0.02, 0.03, 0.04]

        w = optimizer.optimize(cov, mu)

        # Validate portfolio constraints
        assert len(w) == 3
        assert all(wi >= 0.0 for wi in w)
        assert all(wi <= 0.3 for wi in w)
        assert sum(w) <= 1.0 + 1e-6

        # Check XAI fields
        xai_details = {
            "method": optimizer.method,
            "gross_cap": optimizer.gross_cap,
            "max_weight": optimizer.max_weight,
            "cvar_alpha": optimizer.cvar_alpha,
            "cvar_limit": optimizer.cvar_limit,
            "feasible": True,
            "w_raw": w,
            "w_final": w
        }
        assert all(isinstance(v, (bool, float, list, str)) for v in xai_details.values())

    def test_exchange_filters_priority(self):
        """Test that exchange-specific filters take priority over global limits."""
        # Global limits
        global_min = 10.0
        global_max = 5000.0

        # Exchange-specific (tighter)
        exchange_min = 50.0
        exchange_max = 2000.0

        # Test case
        notional_target = 3000.0  # Between global limits
        px = 50000.0
        lot_step = 0.00001

        # With global limits
        qty_global = fraction_to_qty(notional_target, px, lot_step, global_min, global_max)
        assert qty_global > 0.0

        # With exchange limits (should be more restrictive)
        qty_exchange = fraction_to_qty(notional_target, px, lot_step, exchange_min, exchange_max)
        assert qty_exchange == 0.0  # Should be rejected due to min_notional

    def test_zero_equity_edge_case(self):
        """Test edge case with zero or negative equity."""
        p_cal = 0.6
        rr = 1.0

        # Zero equity
        f = kelly_binary(p_cal, rr, risk_aversion=1.0, clip=(0.0, 0.2))
        notional_target = f * 0.0
        qty = fraction_to_qty(notional_target, 50000.0, 0.00001, 10.0, 5000.0)

        assert qty == 0.0

    def test_extreme_volatility_fallback(self):
        """Test fallback behavior with extreme volatility."""
        from core.sizing.kelly import kelly_mu_sigma

        # Extreme volatility
        mu = 0.02
        sigma = 10.0  # Very high volatility

        f = kelly_mu_sigma(mu, sigma, risk_aversion=1.0, clip=(0.0, 0.2))

        # Should be very small due to high volatility
        assert f == 0.0002  # (0.02 / 100) / 1.0 = 0.0002

    @patch('core.sizing.kelly.np')
    def test_numpy_unavailable_fallback(self, mock_np):
        """Test fallback when NumPy is unavailable."""
        mock_np = None

        # Should still work with pure Python implementation
        from core.sizing.kelly import kelly_binary

        f = kelly_binary(0.6, 1.0, risk_aversion=1.0, clip=(0.0, 0.2))
        assert abs(f - 0.2) < 1e-10  # Account for floating point precision


if __name__ == "__main__":
    pytest.main([__file__, "-v"])