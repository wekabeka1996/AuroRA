"""
Tests — Portfolio Optimization
==============================

Test PortfolioOptimizer for Step 2: Sizing/Portfolio.
"""

from __future__ import annotations

import pytest

from core.sizing.portfolio import PortfolioOptimizer


class TestPortfolioOptimizer:
    """Test PortfolioOptimizer class."""

    def test_optimize_box_constraints(self):
        """Test basic box constraints (long-only, gross exposure, max weight)."""
        optimizer = PortfolioOptimizer(
            gross_cap=1.0,
            max_weight=0.3
        )

        # Simple 3-asset case
        cov = [
            [0.04, 0.01, 0.005],
            [0.01, 0.09, 0.02],
            [0.005, 0.02, 0.16]
        ]
        mu = [0.02, 0.03, 0.04]

        w = optimizer.optimize(cov, mu)

        # Check constraints
        assert all(wi >= 0.0 for wi in w)  # Long-only
        assert all(wi <= 0.3 for wi in w)  # Max weight
        assert abs(sum(w) - 1.0) < 1e-6 or sum(w) <= 1.0  # Gross cap

    def test_optimize_cvar_constraint(self):
        """Test CVaR constraint application."""
        optimizer = PortfolioOptimizer(
            cvar_alpha=0.95,
            cvar_limit=0.1  # Tight CVaR limit
        )

        # High volatility assets
        cov = [
            [0.25, 0.1],
            [0.1, 0.36]
        ]
        mu = [0.05, 0.08]

        w = optimizer.optimize(cov, mu)

        # Should have feasible solution
        assert len(w) == 2
        assert all(wi >= 0.0 for wi in w)
        assert abs(sum(w) - 1.0) < 1e-6 or sum(w) <= 1.0

    def test_lw_shrinkage_stability(self):
        """Test Ledoit-Wolf shrinkage with near-singular matrix."""
        optimizer = PortfolioOptimizer(method="lw_shrinkage")

        # Nearly singular covariance matrix
        cov = [
            [1.0, 0.999],
            [0.999, 1.0]
        ]
        mu = [0.02, 0.02]

        w = optimizer.optimize(cov, mu)

        # Should not crash and return valid weights
        assert len(w) == 2
        assert all(wi >= 0.0 for wi in w)
        assert abs(sum(w) - 1.0) < 1e-3  # Allow some tolerance

    def test_single_asset_case(self):
        """Test single asset optimization."""
        optimizer = PortfolioOptimizer()

        cov = [[0.04]]
        mu = [0.02]

        w = optimizer.optimize(cov, mu)

        assert len(w) == 1
        assert abs(w[0] - 1.0) < 1e-6

    def test_empty_inputs(self):
        """Test handling of empty or invalid inputs."""
        optimizer = PortfolioOptimizer()

        # Empty inputs
        w = optimizer.optimize([], [])
        assert w == []

        # Mismatched dimensions
        w = optimizer.optimize([[1.0]], [0.1, 0.2])
        assert w == [0.0, 0.0]

    def test_invalid_covariance_matrix(self):
        """Test handling of invalid covariance matrix."""
        optimizer = PortfolioOptimizer()

        # Negative diagonal (invalid covariance)
        cov = [
            [-0.1, 0.0],
            [0.0, 0.04]
        ]
        mu = [0.02, 0.03]

        w = optimizer.optimize(cov, mu)

        # Should fallback gracefully
        assert len(w) == 2
        assert all(wi >= 0.0 for wi in w)

    def test_extreme_parameters(self):
        """Test extreme parameter values."""
        # Very tight constraints
        optimizer = PortfolioOptimizer(
            gross_cap=0.1,
            max_weight=0.05
        )

        cov = [
            [0.04, 0.01],
            [0.01, 0.09]
        ]
        mu = [0.02, 0.03]

        w = optimizer.optimize(cov, mu)

        # Should respect tight constraints
        assert sum(w) <= 0.1 + 1e-6
        assert all(wi <= 0.05 + 1e-6 for wi in w)
        assert all(wi >= 0.0 for wi in w)

    def test_method_fallback(self):
        """Test fallback when method is not 'lw_shrinkage'."""
        optimizer = PortfolioOptimizer(method="unknown_method")

        cov = [
            [0.04, 0.01],
            [0.01, 0.09]
        ]
        mu = [0.02, 0.03]

        w = optimizer.optimize(cov, mu)

        # Should use fallback method
        assert len(w) == 2
        assert all(wi >= 0.0 for wi in w)
        assert abs(sum(w) - 1.0) < 1e-3


if __name__ == "__main__":
    pytest.main([__file__, "-v"])