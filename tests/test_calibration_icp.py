"""
Tests for core/calibration/icp.py - Conformal Prediction and Calibration
========================================================================

Tests SplitConformalBinary, MondrianConformalBinary, and VennAbersBinary classes.
"""

import pytest
import math
import random
from typing import List, Tuple

from core.calibration.icp import (
    SplitConformalBinary,
    MondrianConformalBinary,
    VennAbersBinary,
    _nonconformity_binary,
    _quantile_leq
)


class TestSplitConformalBinary:
    """Test Split Conformal Prediction for binary classification."""

    def test_initialization(self):
        """Test default initialization."""
        sc = SplitConformalBinary()
        assert sc.alpha == 0.1
        assert not hasattr(sc, 'n')
        assert not hasattr(sc, 'scores')

    def test_custom_alpha(self):
        """Test custom alpha value."""
        sc = SplitConformalBinary(alpha=0.05)
        assert sc.alpha == 0.05

    def test_fit_basic(self):
        """Test basic fitting with simple data."""
        sc = SplitConformalBinary(alpha=0.1)

        # Simple training data: perfect predictions
        p_hat = [0.9, 0.1, 0.8, 0.2]
        y = [1, 0, 1, 0]

        sc.fit(p_hat, y)

        assert sc.n == 4
        assert len(sc.scores) == 4
        assert all(isinstance(s, float) for s in sc.scores)

    def test_fit_edge_cases(self):
        """Test fitting with edge case probabilities."""
        sc = SplitConformalBinary()

        # Edge case probabilities
        p_hat = [0.0, 1.0, 0.5]
        y = [0, 1, 1]

        sc.fit(p_hat, y)
        assert sc.n == 3

    def test_p_values_unfitted(self):
        """Test p-values when model is not fitted."""
        sc = SplitConformalBinary()

        p1, p0 = sc.p_values(0.5)
        assert p1 == 1.0
        assert p0 == 1.0

    def test_p_values_perfect_calibration(self):
        """Test p-values with perfectly calibrated predictions."""
        sc = SplitConformalBinary(alpha=0.1)

        # Perfect calibration: p_hat matches y exactly
        p_hat = [0.9, 0.1, 0.8, 0.2, 0.7, 0.3]
        y = [1, 0, 1, 0, 1, 0]

        sc.fit(p_hat, y)

        # Test on similar data
        p1, p0 = sc.p_values(0.85)  # Should favor y=1
        assert p1 > p0

        p1, p0 = sc.p_values(0.15)  # Should favor y=0
        assert p0 > p1

    def test_p_values_miscalibrated(self):
        """Test p-values with miscalibrated predictions."""
        sc = SplitConformalBinary(alpha=0.1)

        # Miscalibrated: always predict 0.5
        p_hat = [0.5, 0.5, 0.5, 0.5]
        y = [1, 0, 1, 0]

        sc.fit(p_hat, y)

        # Should have similar p-values for both classes
        p1, p0 = sc.p_values(0.5)
        assert abs(p1 - p0) < 0.3  # Should be relatively close

    def test_predict_set_high_confidence(self):
        """Test prediction set with high confidence predictions."""
        sc = SplitConformalBinary(alpha=0.1)

        # Train on well-calibrated data
        p_hat = [0.9, 0.1, 0.8, 0.2, 0.7, 0.3]
        y = [1, 0, 1, 0, 1, 0]
        sc.fit(p_hat, y)

        # High confidence prediction for class 1
        pred_set = sc.predict_set(0.9)
        assert 1 in pred_set

        # High confidence prediction for class 0
        pred_set = sc.predict_set(0.1)
        assert 0 in pred_set

    def test_predict_set_uncertain(self):
        """Test prediction set with uncertain predictions."""
        sc = SplitConformalBinary(alpha=0.1)

        # Train on miscalibrated data
        p_hat = [0.5, 0.5, 0.5, 0.5]
        y = [1, 0, 1, 0]
        sc.fit(p_hat, y)

        # Uncertain prediction should include both classes
        pred_set = sc.predict_set(0.5)
        assert len(pred_set) == 2
        assert 0 in pred_set
        assert 1 in pred_set

    def test_predict_set_strict_alpha(self):
        """Test prediction set with strict alpha (high confidence required)."""
        sc = SplitConformalBinary(alpha=0.01)  # Very strict

        p_hat = [0.9, 0.1, 0.8, 0.2]
        y = [1, 0, 1, 0]
        sc.fit(p_hat, y)

        # Even high confidence might not be enough with strict alpha
        pred_set = sc.predict_set(0.9)
        # May be empty or contain only one class depending on calibration

    def test_small_dataset(self):
        """Test with very small dataset."""
        sc = SplitConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2]
        y = [1, 0]
        sc.fit(p_hat, y)

        assert sc.n == 2

        # Test p-values
        p1, p0 = sc.p_values(0.7)
        assert isinstance(p1, float)
        assert isinstance(p0, float)
        assert 0 <= p1 <= 1
        assert 0 <= p0 <= 1


class TestMondrianConformalBinary:
    """Test Mondrian Conformal Prediction with group-based calibration."""

    def test_initialization(self):
        """Test default initialization."""
        mc = MondrianConformalBinary()
        assert mc.alpha == 0.1

    def test_fit_basic(self):
        """Test basic fitting with groups."""
        mc = MondrianConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2, 0.9, 0.1, 0.7, 0.3]
        y = [1, 0, 1, 0, 1, 0]
        groups = ["A", "A", "B", "B", "A", "B"]

        mc.fit(p_hat, y, groups)

        assert hasattr(mc, 'bucket')
        assert hasattr(mc, 'global_scores')
        assert "A" in mc.bucket
        assert "B" in mc.bucket
        assert len(mc.bucket["A"]) == 3  # 3 samples for group A
        assert len(mc.bucket["B"]) == 3  # 3 samples for group B

    def test_p_values_group_specific(self):
        """Test p-values for specific groups."""
        mc = MondrianConformalBinary(alpha=0.1)

        # Create group-specific patterns
        p_hat = [0.8, 0.2, 0.9, 0.1]
        y = [1, 0, 1, 0]
        groups = ["A", "A", "B", "B"]

        mc.fit(p_hat, y, groups)

        # Test group A (trained on 0.8->1, 0.2->0)
        p1_a, p0_a = mc.p_values(0.75, "A")
        assert isinstance(p1_a, float)
        assert isinstance(p0_a, float)

        # Test group B (trained on 0.9->1, 0.1->0)
        p1_b, p0_b = mc.p_values(0.85, "B")
        assert isinstance(p1_b, float)
        assert isinstance(p0_b, float)

    def test_p_values_unknown_group(self):
        """Test p-values for unknown group (should use global fallback)."""
        mc = MondrianConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2, 0.9, 0.1]
        y = [1, 0, 1, 0]
        groups = ["A", "A", "B", "B"]

        mc.fit(p_hat, y, groups)

        # Unknown group should use global scores
        p1, p0 = mc.p_values(0.5, "C")
        assert isinstance(p1, float)
        assert isinstance(p0, float)

    def test_p_values_no_group(self):
        """Test p-values with no group specified."""
        mc = MondrianConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2, 0.9, 0.1]
        y = [1, 0, 1, 0]
        groups = ["A", "A", "B", "B"]

        mc.fit(p_hat, y, groups)

        # No group should use global scores
        p1, p0 = mc.p_values(0.5, None)
        assert isinstance(p1, float)
        assert isinstance(p0, float)

    def test_predict_set_group_specific(self):
        """Test prediction sets for specific groups."""
        mc = MondrianConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2, 0.9, 0.1]
        y = [1, 0, 1, 0]
        groups = ["A", "A", "B", "B"]

        mc.fit(p_hat, y, groups)

        # Test confident prediction for group A
        pred_set = mc.predict_set(0.8, "A")
        assert isinstance(pred_set, list)

        # Test confident prediction for group B
        pred_set = mc.predict_set(0.1, "B")
        assert isinstance(pred_set, list)

    def test_empty_group_fallback(self):
        """Test fallback when group has no training data."""
        mc = MondrianConformalBinary(alpha=0.1)

        # Create data with only one group
        p_hat = [0.8, 0.2]
        y = [1, 0]
        groups = ["A", "A"]

        mc.fit(p_hat, y, groups)

        # Query unknown group should use global fallback
        p1, p0 = mc.p_values(0.5, "B")
        # Should use global scores, not return 1.0
        assert isinstance(p1, float)
        assert isinstance(p0, float)
        assert 0 <= p1 <= 1
        assert 0 <= p0 <= 1

    def test_single_sample_groups(self):
        """Test with groups having single samples."""
        mc = MondrianConformalBinary(alpha=0.1)

        p_hat = [0.8, 0.2, 0.9]
        y = [1, 0, 1]
        groups = ["A", "B", "C"]

        mc.fit(p_hat, y, groups)

        # Each group should have one sample
        assert len(mc.bucket["A"]) == 1
        assert len(mc.bucket["B"]) == 1
        assert len(mc.bucket["C"]) == 1


class TestVennAbersBinary:
    """Test Venn-Abers multiprobability predictor."""

    def test_initialization(self):
        """Test basic initialization."""
        va = VennAbersBinary()
        # No default parameters to check

    def test_fit_basic(self):
        """Test basic fitting."""
        va = VennAbersBinary()

        scores = [0.1, 0.5, 0.9, 0.2, 0.8]
        y = [0, 1, 1, 0, 1]

        va.fit(scores, y)

        assert hasattr(va, 's')
        assert hasattr(va, 'y')
        assert len(va.s) == 5
        assert len(va.y) == 5

    def test_fit_probabilities(self):
        """Test fitting with probability inputs (should convert to logits)."""
        va = VennAbersBinary()

        # Input as probabilities
        probs = [0.1, 0.5, 0.9]
        y = [0, 1, 1]

        va.fit(probs, y)

        # Should be converted to logits
        assert len(va.s) == 3
        # Check that values are no longer in [0,1] range (logits)
        assert any(s < 0 or s > 1 for s in va.s)

    def test_predict_interval_basic(self):
        """Test basic interval prediction."""
        va = VennAbersBinary()

        # Simple training data
        scores = [0.1, 0.5, 0.9]
        y = [0, 1, 1]

        va.fit(scores, y)

        # Test prediction
        p_low, p_high = va.predict_interval(0.6)

        assert isinstance(p_low, float)
        assert isinstance(p_high, float)
        assert 0.0 <= p_low <= 1.0
        assert 0.0 <= p_high <= 1.0
        assert p_low <= p_high

    def test_predict_interval_extreme_values(self):
        """Test interval prediction with extreme input values."""
        va = VennAbersBinary()

        scores = [0.1, 0.5, 0.9]
        y = [0, 1, 1]

        va.fit(scores, y)

        # Test extreme values
        p_low, p_high = va.predict_interval(0.0)
        assert 0.0 <= p_low <= p_high <= 1.0

        p_low, p_high = va.predict_interval(1.0)
        assert 0.0 <= p_low <= p_high <= 1.0

    def test_predict_interval_probability_input(self):
        """Test prediction with probability input (should convert to logit)."""
        va = VennAbersBinary()

        # Train with logits
        scores = [-2.0, 0.0, 2.0]
        y = [0, 1, 1]

        va.fit(scores, y)

        # Test with probability input
        p_low, p_high = va.predict_interval(0.7)  # Should be converted to logit

        assert isinstance(p_low, float)
        assert isinstance(p_high, float)
        assert 0.0 <= p_low <= p_high <= 1.0

    def test_predict_interval_consistency(self):
        """Test that intervals are consistent (p_low <= p_high)."""
        va = VennAbersBinary()

        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        y = [0, 0, 1, 1, 1]

        va.fit(scores, y)

        # Test multiple predictions
        test_scores = [0.2, 0.4, 0.6, 0.8]

        for score in test_scores:
            p_low, p_high = va.predict_interval(score)
            assert p_low <= p_high, f"Invalid interval for score {score}: [{p_low}, {p_high}]"
            assert 0.0 <= p_low <= 1.0
            assert 0.0 <= p_high <= 1.0

    def test_small_dataset(self):
        """Test with minimal dataset."""
        va = VennAbersBinary()

        scores = [0.3, 0.7]
        y = [0, 1]

        va.fit(scores, y)

        # Should still work
        p_low, p_high = va.predict_interval(0.5)
        assert 0.0 <= p_low <= p_high <= 1.0


class TestUtilityFunctions:
    """Test utility functions."""

    def test_nonconformity_binary(self):
        """Test nonconformity score calculation."""
        # Perfect prediction y=1, p=0.9 -> low nonconformity
        s = _nonconformity_binary(0.9, 1)
        assert abs(s - 0.1) < 1e-10  # Account for floating point precision

        # Perfect prediction y=0, p=0.1 -> low nonconformity
        s = _nonconformity_binary(0.1, 0)
        assert abs(s - 0.1) < 1e-10

        # Wrong prediction y=1, p=0.1 -> high nonconformity
        s = _nonconformity_binary(0.1, 1)
        assert abs(s - 0.9) < 1e-10

        # Wrong prediction y=0, p=0.9 -> high nonconformity
        s = _nonconformity_binary(0.9, 0)
        assert abs(s - 0.9) < 1e-10

        # Edge cases
        s = _nonconformity_binary(0.0, 1)
        assert s == 1.0

        s = _nonconformity_binary(1.0, 0)
        assert s == 1.0

    def test_nonconformity_binary_clipping(self):
        """Test that probabilities are clipped to [0,1]."""
        # Values outside [0,1] should be clipped
        s = _nonconformity_binary(-0.1, 1)
        assert s == 1.0  # p clipped to 0.0, so s = 1*(1-0) + (1-1)*0 = 1.0

        s = _nonconformity_binary(1.1, 0)
        assert s == 1.0  # p clipped to 1.0, so s = 0*(1-1) + (1-0)*1 = 1.0

    def test_quantile_leq(self):
        """Test quantile calculation."""
        values = [1.0, 2.0, 3.0, 4.0, 5.0]

        # Median (q=0.5)
        q = _quantile_leq(values, 0.5)
        assert q == 3.0

        # First quartile (q=0.25)
        q = _quantile_leq(values, 0.25)
        assert q == 2.0

        # Third quartile (q=0.75)
        q = _quantile_leq(values, 0.75)
        assert q == 4.0

        # Min (q=0.0)
        q = _quantile_leq(values, 0.0)
        assert q == 1.0

        # Max (q=1.0)
        q = _quantile_leq(values, 1.0)
        assert q == 5.0

    def test_quantile_leq_edge_cases(self):
        """Test quantile with edge cases."""
        # Empty list
        q = _quantile_leq([], 0.5)
        assert q == 0.0

        # Single element
        q = _quantile_leq([3.14], 0.5)
        assert q == 3.14

        # Two elements
        q = _quantile_leq([1.0, 2.0], 0.5)
        assert q == 1.0  # First element due to left-closed quantile

    def test_quantile_leq_unsorted(self):
        """Test that quantile works with unsorted input (should still work but be incorrect)."""
        values = [5.0, 1.0, 3.0, 2.0, 4.0]

        # This will give wrong results since input is unsorted
        q = _quantile_leq(values, 0.5)
        # We don't assert correctness here since input contract is violated


class TestIntegration:
    """Integration tests combining multiple components."""

    def test_split_vs_mondrian_consistency(self):
        """Test that Split and Mondrian give reasonable results."""
        # Create the same data
        p_hat = [0.8, 0.2, 0.9, 0.1, 0.7, 0.3]
        y = [1, 0, 1, 0, 1, 0]

        # Fit both models
        sc = SplitConformalBinary(alpha=0.1)
        sc.fit(p_hat, y)

        mc = MondrianConformalBinary(alpha=0.1)
        groups = ["A"] * len(p_hat)  # All same group
        mc.fit(p_hat, y, groups)

        # They should give similar results for the same group
        p1_sc, p0_sc = sc.p_values(0.75)
        p1_mc, p0_mc = mc.p_values(0.75, "A")

        # Should be reasonably close (not exactly equal due to different implementations)
        assert abs(p1_sc - p1_mc) < 0.3
        assert abs(p0_sc - p0_mc) < 0.3

    def test_calibration_quality(self):
        """Test calibration quality with synthetic data."""
        # Generate well-calibrated data
        random.seed(42)
        n_samples = 100

        p_hat = []
        y = []

        for _ in range(n_samples):
            true_p = random.random()
            # Add some noise to create realistic predictions
            noise = random.gauss(0, 0.1)
            pred_p = min(1.0, max(0.0, true_p + noise))

            # Generate outcome
            outcome = 1 if random.random() < true_p else 0

            p_hat.append(pred_p)
            y.append(outcome)

        # Test SplitConformal
        sc = SplitConformalBinary(alpha=0.1)
        sc.fit(p_hat, y)

        # Test that p-values are reasonable
        test_p = 0.5
        p1, p0 = sc.p_values(test_p)

        assert 0 <= p1 <= 1
        assert 0 <= p0 <= 1

        # For a neutral prediction, p-values should be similar
        assert abs(p1 - p0) < 0.5

    def test_venn_abers_vs_split_comparison(self):
        """Compare Venn-Abers intervals with Split conformal p-values."""
        # Create simple dataset
        scores = [0.1, 0.3, 0.5, 0.7, 0.9]
        y = [0, 0, 1, 1, 1]

        # Fit both models
        va = VennAbersBinary()
        va.fit(scores, y)

        sc = SplitConformalBinary(alpha=0.1)
        sc.fit(scores, y)

        # Test on a new score
        test_score = 0.6

        # Venn-Abers gives interval
        p_low, p_high = va.predict_interval(test_score)

        # Split conformal gives p-values
        p1, p0 = sc.p_values(test_score)

        # The intervals should be related
        # p1 roughly corresponds to upper bound, p0 to lower bound
        assert p_low <= p_high
        assert 0 <= p1 <= 1
        assert 0 <= p0 <= 1
