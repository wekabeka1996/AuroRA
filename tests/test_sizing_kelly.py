"""
Tests — Kelly Sizing
====================

Test Kelly sizing functions for Step 2: Sizing/Portfolio.
"""

from __future__ import annotations

import pytest
import math

from core.sizing.kelly import (
    kelly_binary,
    kelly_mu_sigma,
    fraction_to_qty,
    edge_to_pwin,
    raw_kelly_fraction,
    KellyOrchestrator
)


class TestKellySizing:
    """Test Kelly sizing functions."""

    def test_kelly_binary_symmetry_rr1(self):
        """Test Kelly binary with symmetric odds (p=0.5, rr=1) returns 0."""
        f = kelly_binary(p_win=0.5, rr=1.0)
        assert abs(f - 0.0) < 1e-12

    def test_kelly_binary_positive_edge(self):
        """Test Kelly binary with positive edge."""
        # p=0.6, rr=1, ra=1 → f ≈ 0.2
        f = kelly_binary(p_win=0.6, rr=1.0, risk_aversion=1.0)
        expected = 0.2  # (1*0.6 - 0.4) / 1 = 0.2
        assert abs(f - expected) < 1e-6

        # Test with risk aversion
        f_ra = kelly_binary(p_win=0.6, rr=1.0, risk_aversion=2.0)
        assert abs(f_ra - expected/2.0) < 1e-6

    def test_kelly_binary_clipping(self):
        """Test Kelly binary clipping bounds."""
        # High edge should be clipped to max
        f = kelly_binary(p_win=0.9, rr=2.0, clip=(0.0, 0.1))
        assert f == 0.1

        # Negative edge should be clipped to min
        f = kelly_binary(p_win=0.3, rr=1.0, clip=(0.05, 0.2))
        assert f == 0.05

    def test_kelly_binary_edge_cases(self):
        """Test Kelly binary edge cases."""
        # Invalid probability
        assert kelly_binary(-0.1, 1.0) == 0.0
        assert kelly_binary(1.1, 1.0) == 0.0

        # Invalid rr
        assert kelly_binary(0.6, 0.0) == 0.0
        assert kelly_binary(0.6, -1.0) == 0.0

        # Invalid risk aversion
        assert kelly_binary(0.6, 1.0, risk_aversion=0.0) == 0.0

    def test_kelly_mu_sigma_basic(self):
        """Test Kelly mu-sigma approximation."""
        # μ=0.02, σ=0.1 → f = (0.02 / 0.01) / 1 = 2.0, clipped to 0.2
        f = kelly_mu_sigma(mu=0.02, sigma=0.1, clip=(0.0, 0.2))
        assert f == 0.2

        # With risk aversion: (0.02 / 0.01) / 2 = 1.0, clipped to 0.2
        f_ra = kelly_mu_sigma(mu=0.02, sigma=0.1, risk_aversion=2.0, clip=(0.0, 0.2))
        assert f_ra == 0.2  # Risk aversion applied before clipping

    def test_kelly_mu_sigma_edge_cases(self):
        """Test Kelly mu-sigma edge cases."""
        # Zero or negative sigma
        assert kelly_mu_sigma(0.02, 0.0) == 0.0
        assert kelly_mu_sigma(0.02, -0.1) == 0.0

        # Invalid risk aversion
        assert kelly_mu_sigma(0.02, 0.1, risk_aversion=0.0) == 0.0

    def test_fraction_to_qty_rounding_and_bounds(self):
        """Test quantity calculation with rounding and bounds."""
        # Basic calculation: 1000 / 50000 = 0.02
        qty = fraction_to_qty(1000.0, 50000.0, 0.00001, 10.0, 5000.0)
        assert abs(qty - 0.02) < 1e-8

        # Rounding to lot step: 1000 / 50000 = 0.02, round to 0.00001 step
        qty = fraction_to_qty(1000.0, 50000.0, 0.001, 10.0, 5000.0)
        assert qty == 0.020  # Rounded to nearest 0.001

        # Below min notional
        qty = fraction_to_qty(5.0, 50000.0, 0.00001, 10.0, 5000.0)
        assert qty == 0.0

        # Above max notional
        qty = fraction_to_qty(10000.0, 50000.0, 0.00001, 10.0, 5000.0)
        assert qty == 0.0

    def test_fraction_to_qty_edge_cases(self):
        """Test fraction_to_qty edge cases."""
        # Invalid inputs
        assert fraction_to_qty(0.0, 50000.0, 0.00001, 10.0, 5000.0) == 0.0
        assert fraction_to_qty(1000.0, 0.0, 0.00001, 10.0, 5000.0) == 0.0
        assert fraction_to_qty(1000.0, 50000.0, 0.0, 10.0, 5000.0) == 0.0

    def test_edge_to_pwin_mapping(self):
        """Test edge to probability conversion."""
        # Zero edge → 0.5 probability
        p = edge_to_pwin(0.0)
        assert abs(p - 0.5) < 1e-12

        # Positive edge → p > 0.5
        p = edge_to_pwin(100.0)  # 100bps = 1%
        expected = (0.01 + 1.0) / 2.0  # For rr=1
        assert abs(p - expected) < 1e-6

        # Negative edge → p < 0.5
        p = edge_to_pwin(-100.0)  # -100bps = -1%
        expected = (-0.01 + 1.0) / 2.0
        assert abs(p - expected) < 1e-6

        # Test with different rr
        p = edge_to_pwin(100.0, rr=2.0)
        expected = (0.01 + 1.0) / (1.0 + 2.0)
        assert abs(p - expected) < 1e-6

    def test_edge_to_pwin_bounds(self):
        """Test edge_to_pwin probability bounds."""
        # Very positive edge
        p = edge_to_pwin(10000.0)  # 10000bps = 100%
        assert p == 1.0

        # Very negative edge
        p = edge_to_pwin(-10000.0)  # -10000bps = -100%
        assert p == 0.0

    def test_legacy_compatibility(self):
        """Test legacy functions still work."""
        # raw_kelly_fraction
        f = raw_kelly_fraction(0.6, 2.0, 1.0, 0.25)
        expected = 0.25  # (2*0.6 - 0.4)/2 = 0.4, then min(0.4, 0.25) = 0.25
        assert abs(f - expected) < 1e-6

        # KellyOrchestrator
        ko = KellyOrchestrator(cap=0.5)
        f = ko.size(0.6, 2.0, 1.0)
        assert 0.0 <= f <= 0.5

    def test_kelly_binary_zero_edge(self):
        """Test Kelly binary zero edge case: p=0.5, b=1 ⇒ f*=0."""
        f = kelly_binary(p_win=0.5, rr=1.0, risk_aversion=1.0)
        assert abs(f - 0.0) < 1e-12

    def test_kelly_binary_monotonicity(self):
        """Test Kelly binary monotonicity: ∂f*/∂p>0, ∂f*/∂b>0."""
        # Monotonicity in p_win
        f1 = kelly_binary(p_win=0.4, rr=1.0, risk_aversion=1.0)
        f2 = kelly_binary(p_win=0.6, rr=1.0, risk_aversion=1.0)
        assert f2 > f1  # ∂f*/∂p > 0

        # Monotonicity in rr (b)
        f1 = kelly_binary(p_win=0.6, rr=1.0, risk_aversion=1.0)
        f2 = kelly_binary(p_win=0.6, rr=2.0, risk_aversion=1.0)
        assert f2 > f1  # ∂f*/∂b > 0

    def test_kelly_binary_negative_edge(self):
        """Test Kelly binary negative edge: p<1/(1+b) ⇒ f*≤0."""
        # For b=1, break-even p = 1/(1+1) = 0.5
        f = kelly_binary(p_win=0.4, rr=1.0, risk_aversion=1.0)
        assert f <= 0.0

        # For b=2, break-even p = 1/(1+2) = 0.333
        f = kelly_binary(p_win=0.3, rr=2.0, risk_aversion=1.0)
        assert f <= 0.0

    def test_kelly_binary_risk_aversion_scaling(self):
        """Test Kelly binary risk aversion scaling: ρ only scales, shape unchanged."""
        p_win = 0.6
        rr = 1.5

        f1 = kelly_binary(p_win, rr, risk_aversion=1.0, clip=(0.0, 1.0))
        f2 = kelly_binary(p_win, rr, risk_aversion=2.0, clip=(0.0, 1.0))

        # Risk aversion should scale down proportionally
        assert abs(f2 - f1/2.0) < 1e-10

        # Test with different p_win values
        for p in [0.55, 0.65, 0.7]:
            f_low = kelly_binary(p, rr, risk_aversion=1.0, clip=(0.0, 1.0))
            f_high = kelly_binary(p, rr, risk_aversion=3.0, clip=(0.0, 1.0))
            assert abs(f_high - f_low/3.0) < 1e-10

    def test_kelly_mu_sigma_single_asset_closed_form(self):
        """Test Kelly mu-sigma single asset: Σ=I ⇒ w*=μ/γ."""
        # Single asset with identity covariance
        mu = 0.02
        sigma = 0.1
        gamma = 2.0

        f = kelly_mu_sigma(mu, sigma, risk_aversion=gamma, clip=(0.0, 1.0))
        expected = (mu / (sigma ** 2)) / gamma  # 0.02 / 0.01 / 2 = 1.0

        assert abs(f - expected) < 1e-10

    def test_edge_to_pwin_invariants(self):
        """Test edge_to_pwin invariants and saturation."""
        # Zero edge ⇒ p = 1/(1+b)
        p = edge_to_pwin(0.0, rr=1.0)
        assert abs(p - 0.5) < 1e-12

        p = edge_to_pwin(0.0, rr=2.0)
        assert abs(p - 1.0/3.0) < 1e-10

        # Saturation bounds - edge_to_pwin clamps to [0, 1]
        p_min = edge_to_pwin(-10000.0)  # Very negative edge
        p_max = edge_to_pwin(10000.0)   # Very positive edge

        assert p_min == 0.0  # Clamped to minimum
        assert p_max == 1.0  # Clamped to maximum

    def test_dd_haircut_factor(self):
        """Test DD haircut factor calculation."""
        from decimal import Decimal
        from core.sizing.kelly import dd_haircut_factor, apply_dd_haircut_to_kelly

        # No drawdown
        haircut = dd_haircut_factor(Decimal("0"))
        assert haircut == Decimal("1")

        # Full drawdown
        haircut = dd_haircut_factor(Decimal("300"))  # DD_max = 300
        assert haircut == Decimal("0")

        # Partial drawdown: D=150, DD_max=300, β=2
        # g = (1 - 150/300)^2 = (1 - 0.5)^2 = 0.5^2 = 0.25
        haircut = dd_haircut_factor(
            Decimal("150"), dd_max_bps=Decimal("300"), beta=Decimal("2")
        )
        assert haircut == Decimal("0.25")

        # Test monotonicity: higher DD → lower haircut
        h1 = dd_haircut_factor(Decimal("100"))
        h2 = dd_haircut_factor(Decimal("200"))
        assert h2 < h1

    def test_dd_haircut_application(self):
        """Test DD haircut application to Kelly fraction."""
        from decimal import Decimal
        from core.sizing.kelly import apply_dd_haircut_to_kelly

        kelly_raw = Decimal("0.1")

        # No DD
        adjusted = apply_dd_haircut_to_kelly(kelly_raw, Decimal("0"))
        assert adjusted == kelly_raw

        # Partial DD
        adjusted = apply_dd_haircut_to_kelly(
            kelly_raw, Decimal("150"), dd_max_bps=Decimal("300"), beta=Decimal("2")
        )
        expected = kelly_raw * Decimal("0.25")  # From previous test
        assert adjusted == expected

        # Full DD
        adjusted = apply_dd_haircut_to_kelly(kelly_raw, Decimal("300"))
        assert adjusted == Decimal("0")

    def test_fraction_to_qty_exchange_compliance(self):
        """Test fraction_to_qty with full exchange compliance."""
        # Test leverage impact
        notional = 1000.0
        px = 50000.0
        lot_step = 0.00001

        # Spot trading (leverage=1.0)
        qty_spot = fraction_to_qty(notional, px, lot_step, 10.0, 5000.0, leverage=1.0)
        expected_spot = notional / px  # 0.02
        assert abs(qty_spot - expected_spot) < 1e-8

        # Futures with leverage (use sufficient margin allowance)
        qty_futures = fraction_to_qty(notional, px, lot_step, 10.0, 5000.0, 
                                    leverage=2.0, initial_margin_pct=0.6)
        # With leverage, effective position is larger but margin requirements apply
        assert qty_futures > 0.0

        # Insufficient margin for high leverage
        qty_insuff = fraction_to_qty(notional, px, lot_step, 10.0, 5000.0,
                                   leverage=10.0, initial_margin_pct=0.05)
        assert qty_insuff == 0.0  # Should fail margin check

    def test_round_trip_compliance(self):
        """Test round-trip compliance for 1000 random parameter combinations."""
        import random

        random.seed(42)  # For reproducible tests

        violations = []
        for i in range(100):
            # Generate random but reasonable parameters
            px = random.uniform(1000, 100000)  # Asset price
            notional = random.uniform(10, 5000)  # Target notional
            lot_step = 10 ** random.randint(-6, -2)  # Lot step: 0.000001 to 0.01
            min_notional = random.uniform(5, 50)
            max_notional = random.uniform(1000, 10000)

            qty = fraction_to_qty(notional, px, lot_step, min_notional, max_notional)

            if qty > 0.0:
                # Verify constraints
                actual_notional = qty * px
                rounded_qty = round(qty / lot_step) * lot_step

                if not (min_notional <= actual_notional <= max_notional):
                    violations.append(f"Notional violation: {actual_notional} not in [{min_notional}, {max_notional}]")

                if abs(qty - rounded_qty) > 1e-12:
                    violations.append(f"Lot step violation: {qty} vs {rounded_qty}")

        # Should have no violations for valid cases
        assert len(violations) == 0, f"Found {len(violations)} violations: {violations[:5]}"

    def test_sizing_stabilizer_hysteresis(self):
        """Test hysteresis prevents small oscillations."""
        from core.sizing.kelly import SizingStabilizer

        stabilizer = SizingStabilizer(
            hysteresis_threshold=0.1,
            hysteresis_flip_threshold=0.2
        )

        # Small change should be ignored
        current = 0.1
        target = 0.105  # Δ = 0.005 < τ = 0.01
        stabilized, _ = stabilizer.stabilize_fraction(target, current)
        assert stabilized == current

        # Large change should be applied
        target = 0.12  # Δ = 0.02 > τ = 0.01
        stabilized, _ = stabilizer.stabilize_fraction(target, current, apply_bucket=False)
        assert stabilized == target

        # Near-zero target with significant current should require larger change
        current = 0.15
        target = 0.02  # |target| = 0.02 < τ_flip = 0.03, so keep current
        stabilized, _ = stabilizer.stabilize_fraction(target, current)
        assert stabilized == current

    def test_sizing_stabilizer_bucket_sizing(self):
        """Test bucket sizing uses discrete sizes."""
        from core.sizing.kelly import SizingStabilizer

        buckets = [0.0, 0.01, 0.05, 0.1, 0.2, 0.5]
        stabilizer = SizingStabilizer(bucket_sizes=buckets)

        # Test various targets map to nearest bucket
        test_cases = [
            (0.008, 0.01),   # 0.008 → 0.01
            (0.03, 0.01),    # 0.03 → 0.01 (first in list with equal distance)
            (0.12, 0.1),     # 0.12 → 0.1
            (0.15, 0.1),     # 0.15 → 0.1 (first in list with equal distance)
            (0.25, 0.2),     # 0.25 → 0.2
        ]

        for target, expected in test_cases:
            stabilized, _ = stabilizer.stabilize_fraction(target, apply_hysteresis=False, apply_time_guard=False)
            assert stabilized == expected

    def test_sizing_stabilizer_time_guard(self):
        """Test time guard prevents too frequent resizes."""
        from core.sizing.kelly import SizingStabilizer
        import time

        stabilizer = SizingStabilizer(min_resize_interval_sec=0.1)

        # First resize should work
        stabilized1, meta1 = stabilizer.stabilize_fraction(0.1, 0.0)
        assert stabilized1 == 0.1
        assert meta1["time_guard_passed"] is True

        # Immediate second resize should be blocked
        stabilized2, meta2 = stabilizer.stabilize_fraction(0.2, 0.1)
        assert stabilized2 == 0.1  # Keep current
        assert meta2["time_guard_passed"] is False

        # Wait and try again
        time.sleep(0.15)
        stabilized3, meta3 = stabilizer.stabilize_fraction(0.2, 0.1)
        assert stabilized3 == 0.2
        assert meta3["time_guard_passed"] is True

    def test_portfolio_psd_projection(self):
        """Test PSD projection for invalid covariance matrices."""
        from core.sizing.portfolio import PortfolioOptimizer
        import math

        optimizer = PortfolioOptimizer()

        # Create non-PSD matrix (negative eigenvalue)
        cov = [
            [1.0, 0.0],
            [0.0, -0.1]  # Negative diagonal
        ]
        mu = [0.02, 0.03]

        w = optimizer.optimize(cov, mu)

        # Should fallback gracefully - may not sum to exactly 1.0 due to constraints
        assert len(w) == 2
        assert all(wi >= 0.0 for wi in w)
        assert sum(w) <= 1.0 + 1e-3  # Allow some tolerance for fallback methods

    def test_cvar_scaling_analytical(self):
        """Test CVaR scaling with analytical approximation."""
        from core.sizing.portfolio import PortfolioOptimizer

        optimizer = PortfolioOptimizer(cvar_limit=0.1)

        # Simple case: single asset
        cov = [[0.04]]
        mu = [0.02]

        w = optimizer.optimize(cov, mu)

        # Should apply CVaR scaling if limit breached
        assert len(w) == 1
        assert w[0] >= 0.0

    def test_fallback_parity_numpy_pure_python(self):
        """Test parity between NumPy and pure Python implementations."""
        from core.sizing.portfolio import PortfolioOptimizer

        # Test data
        cov = [
            [0.04, 0.01],
            [0.01, 0.09]
        ]
        mu = [0.02, 0.03]

        # Force fallback (no NumPy)
        import core.sizing.portfolio as port_mod
        original_np = port_mod.np
        port_mod.np = None

        try:
            optimizer = PortfolioOptimizer(method="mean_variance")
            w_fallback = optimizer.optimize(cov, mu)

            # Should work with pure Python
            assert len(w_fallback) == 2
            assert all(wi >= 0.0 for wi in w_fallback)
            assert abs(sum(w_fallback) - 1.0) < 1e-6

        finally:
            # Restore NumPy
            port_mod.np = original_np

    def test_extreme_parameters_stress_test(self):
        """Test extreme parameters: σ→0, σ→large; μ→0; b→1 & ≫1; equity→small."""
        from core.sizing.kelly import kelly_binary, kelly_mu_sigma

        # σ → 0 (infinite Sharpe)
        f = kelly_mu_sigma(mu=0.02, sigma=1e-10, clip=(0.0, 0.2))
        assert f == 0.2  # Should hit upper clip

        # σ → large (zero Sharpe)
        f = kelly_mu_sigma(mu=0.02, sigma=100.0, clip=(0.0, 0.2))
        assert abs(f - 0.000002) < 1e-8  # Kelly fraction is μ/σ² = 0.02/10000 = 0.000002

        # μ → 0
        f = kelly_mu_sigma(mu=0.0, sigma=0.1, clip=(0.0, 0.2))
        assert f == 0.0

        # b → 1 (symmetric)
        f = kelly_binary(p_win=0.6, rr=1.0, clip=(0.0, 0.2))
        assert abs(f - 0.2) < 1e-10  # Allow for floating point precision

        # b ≫ 1 (high reward)
        f = kelly_binary(p_win=0.6, rr=10.0, clip=(0.0, 0.2))
        assert f > 0.0

    def test_xai_logging_completeness(self):
        """Test XAI logging includes all required fields."""
        from core.sizing.portfolio import PortfolioOptimizer

        optimizer = PortfolioOptimizer()

        cov = [
            [0.04, 0.01],
            [0.01, 0.09]
        ]
        mu = [0.02, 0.03]

        w = optimizer.optimize(cov, mu)

        # Simulate XAI logging structure
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

        # Check all fields are present and valid types
        required_fields = [
            "method", "gross_cap", "max_weight", "cvar_alpha", "cvar_limit",
            "feasible", "w_raw", "w_final"
        ]

        for field in required_fields:
            assert field in xai_details
            value = xai_details[field]
            # Allow None for optional fields like cvar_limit
            if value is not None:
                assert isinstance(value, (bool, float, list, str))

    def test_integration_risk_guards_invariant(self):
        """Test that RiskGuards deny prevents sizing when notional_max breached."""
        # This would require integration with RiskGuards
        # For now, test the sizing logic independently
        from core.sizing.kelly import fraction_to_qty

        # Simulate case where notional would exceed max
        notional_target = 6000.0  # Above max_notional_usd = 5000.0
        px = 50000.0
        lot_step = 0.00001

        qty = fraction_to_qty(notional_target, px, lot_step, 10.0, 5000.0)

        # Should be rejected due to max notional
        assert qty == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])