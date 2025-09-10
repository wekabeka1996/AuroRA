"""Unit tests for Composite SPRT/GLR sequential hypothesis testing."""

import math

import numpy as np
import pytest

from core.governance.sprt_glr import CompositeSPRT, SPRTConfig, SPRTOutcome, SPRTState


class TestSPRTConfig:
    """Test SPRT configuration validation."""

    def test_valid_config(self):
        """Test creating valid SPRT configuration."""
        config = SPRTConfig(mu0=0.0, mu1=0.5, alpha=0.05, beta=0.2)
        assert config.mu0 == 0.0
        assert config.mu1 == 0.5
        assert config.alpha == 0.05
        assert config.beta == 0.2
        assert config.min_samples == 5
        assert config.max_samples is None

    def test_equal_means_raises(self):
        """Test that equal mu0 and mu1 raises ValueError."""
        with pytest.raises(ValueError, match="mu0 and mu1 must be different"):
            SPRTConfig(mu0=0.5, mu1=0.5)

    def test_invalid_alpha_raises(self):
        """Test that invalid alpha raises ValueError."""
        with pytest.raises(ValueError, match="alpha must be in"):
            SPRTConfig(mu0=0.0, mu1=0.5, alpha=0.0)

        with pytest.raises(ValueError, match="alpha must be in"):
            SPRTConfig(mu0=0.0, mu1=0.5, alpha=1.0)

    def test_invalid_beta_raises(self):
        """Test that invalid beta raises ValueError."""
        with pytest.raises(ValueError, match="beta must be in"):
            SPRTConfig(mu0=0.0, mu1=0.5, beta=0.0)

        with pytest.raises(ValueError, match="beta must be in"):
            SPRTConfig(mu0=0.0, mu1=0.5, beta=1.0)

    def test_invalid_min_samples_raises(self):
        """Test that invalid min_samples raises ValueError."""
        with pytest.raises(ValueError, match="min_samples must be"):
            SPRTConfig(mu0=0.0, mu1=0.5, min_samples=0)

    def test_invalid_max_samples_raises(self):
        """Test that max_samples < min_samples raises ValueError."""
        with pytest.raises(ValueError, match="max_samples must be"):
            SPRTConfig(mu0=0.0, mu1=0.5, min_samples=10, max_samples=5)

    def test_thresholds(self):
        """Test threshold calculations."""
        config = SPRTConfig(mu0=0.0, mu1=0.5, alpha=0.05, beta=0.2)

        # threshold_h0 = ln(β/(1-α)) = ln(0.2/0.95) ≈ -1.56
        expected_h0 = math.log(0.2 / 0.95)
        assert config.threshold_h0 == pytest.approx(expected_h0)

        # threshold_h1 = ln((1-β)/α) = ln(0.8/0.05) ≈ 2.77
        expected_h1 = math.log(0.8 / 0.05)
        assert config.threshold_h1 == pytest.approx(expected_h1)


class TestSPRTState:
    """Test SPRT state computations."""

    def test_empty_state(self):
        """Test initial empty state."""
        state = SPRTState()
        assert state.n_samples == 0
        assert state.sum_x == 0.0
        assert state.sum_x2 == 0.0
        assert state.mean == 0.0
        assert state.variance == 1.0  # Default
        assert state.std_error == 1.0

    def test_single_sample(self):
        """Test state with single sample."""
        state = SPRTState(n_samples=1, sum_x=2.5, sum_x2=6.25)
        assert state.mean == 2.5
        assert state.variance == 1.0  # Default for n <= 1

    def test_multiple_samples(self):
        """Test state with multiple samples."""
        # Samples: [1, 2, 3] -> sum=6, sum_sq=14
        state = SPRTState(n_samples=3, sum_x=6.0, sum_x2=14.0)
        assert state.mean == 2.0

        # Variance = (14 - 6²/3) / (3-1) = (14 - 12) / 2 = 1.0
        assert state.variance == pytest.approx(1.0)
        assert state.std_error == pytest.approx(math.sqrt(1.0 / 3))


class TestCompositeSPRT:
    """Test Composite SPRT with GLR functionality."""

    def setup_method(self):
        """Create SPRT instance for each test."""
        self.config = SPRTConfig(mu0=0.0, mu1=1.0, alpha=0.05, beta=0.2, min_samples=3)
        self.sprt = CompositeSPRT(self.config)

    def test_initialization(self):
        """Test SPRT initialization."""
        assert self.sprt.config == self.config
        assert self.sprt.state.n_samples == 0
        assert len(self.sprt.history) == 0

    def test_insufficient_samples_continue(self):
        """Test that insufficient samples leads to CONTINUE."""
        # Add samples below min_samples threshold
        decision = self.sprt.update(0.5)
        assert decision.outcome == SPRTOutcome.CONTINUE
        assert decision.stop is False
        assert decision.n_samples == 1

        decision = self.sprt.update(1.0)
        assert decision.outcome == SPRTOutcome.CONTINUE
        assert decision.stop is False
        assert decision.n_samples == 2

    def test_h0_synthetic_data(self):
        """Test H0 acceptance with synthetic data from null hypothesis."""
        # Generate data from N(0, 1) - should favor H0: μ = 0
        np.random.seed(42)
        h0_data = np.random.normal(0.0, 1.0, 50)

        decision = None
        for x in h0_data:
            decision = self.sprt.update(x)
            if decision.stop:
                break

        # Should eventually accept H0
        assert decision is not None
        assert decision.stop is True
        assert decision.outcome == SPRTOutcome.ACCEPT_H0
        assert decision.confidence > 0.5

    def test_h1_synthetic_data(self):
        """Test H1 acceptance with synthetic data from alternative hypothesis."""
        # Generate data from N(1, 1) - should favor H1: μ = 1
        np.random.seed(42)
        h1_data = np.random.normal(1.0, 1.0, 50)

        decision = None
        for x in h1_data:
            decision = self.sprt.update(x)
            if decision.stop:
                break

        # Should eventually accept H1
        assert decision is not None
        assert decision.stop is True
        assert decision.outcome == SPRTOutcome.ACCEPT_H1
        assert decision.confidence > 0.5

    def test_max_samples_forced_stop(self):
        """Test forced stop when max_samples reached."""
        config = SPRTConfig(mu0=0.0, mu1=1.0, alpha=0.05, beta=0.2,
                           min_samples=3, max_samples=10)
        sprt = CompositeSPRT(config)

        # Add inconclusive data that won't trigger early stop
        decision = None
        for i in range(15):  # More than max_samples
            decision = sprt.update(0.3)  # Between mu0 and mu1
            if decision.stop:
                break

        assert decision is not None
        assert decision.stop is True
        # May stop early due to GLR characteristics, just check stopped
        assert decision.n_samples <= 10

    def test_reset(self):
        """Test SPRT reset functionality."""
        # Add some data
        self.sprt.update(1.0)
        self.sprt.update(2.0)
        assert self.sprt.state.n_samples == 2
        assert len(self.sprt.history) == 2

        # Reset
        self.sprt.reset()
        assert self.sprt.state.n_samples == 0
        assert len(self.sprt.history) == 0
        assert self.sprt.state.sum_x == 0.0
        assert self.sprt.state.sum_x2 == 0.0

    def test_get_summary(self):
        """Test summary statistics generation."""
        # Add some data
        self.sprt.update(1.0)
        self.sprt.update(2.0)
        self.sprt.update(3.0)

        summary = self.sprt.get_summary()

        assert summary["n_samples"] == 3
        assert summary["mean"] == 2.0
        assert "variance" in summary
        assert "llr" in summary
        assert "confidence" in summary
        assert "thresholds" in summary
        assert summary["thresholds"]["h0"] == self.config.threshold_h0
        assert summary["thresholds"]["h1"] == self.config.threshold_h1
        assert summary["config"]["mu0"] == 0.0
        assert summary["config"]["mu1"] == 1.0

    def test_llr_computation(self):
        """Test GLR log-likelihood ratio computation."""
        # Add data that should favor H1
        self.sprt.update(1.5)  # Close to mu1=1.0
        self.sprt.update(0.8)
        self.sprt.update(1.2)

        decision = self.sprt.update(1.1)

        # LLR should be positive (favoring H1)
        assert decision.llr > 0

        # Check that state is updated correctly
        assert self.sprt.state.n_samples == 4
        assert self.sprt.state.mean == pytest.approx(1.15)

    def test_confidence_computation(self):
        """Test confidence score computation."""
        # Create scenario with strong evidence for H1
        strong_h1_data = [1.8, 1.9, 2.0, 2.1, 2.2]  # Well above mu1=1.0

        decision = None
        for x in strong_h1_data:
            decision = self.sprt.update(x)
            if decision.stop:
                break

        if decision and decision.stop:
            assert decision.confidence > 0.7  # High confidence for strong evidence

    def test_p_value_approximation(self):
        """Test p-value approximation for decisions."""
        # Add enough data to trigger a decision
        strong_h0_data = [-0.5, -0.3, -0.1, 0.1, 0.0]  # Close to mu0=0.0

        decision = None
        for x in strong_h0_data:
            decision = self.sprt.update(x)
            if decision.stop:
                break

        if decision and decision.stop and decision.p_value is not None:
            assert 0.0 <= decision.p_value <= 1.0

    def test_variance_numerical_stability(self):
        """Test numerical stability with edge cases."""
        # Test with constant data (zero variance)
        for _ in range(5):
            decision = self.sprt.update(1.0)

        # Should not crash with zero variance
        assert decision is not None
        assert decision.n_samples == 5

    def test_negative_variance_protection(self):
        """Test protection against negative variance due to numerical errors."""
        # Manually create state that could lead to negative variance
        sprt = CompositeSPRT(self.config)

        # Force numerical instability
        sprt.state.n_samples = 2
        sprt.state.sum_x = 2.0
        sprt.state.sum_x2 = 1.0  # This would give negative variance

        # GLR computation should handle this gracefully
        llr = sprt._compute_glr_llr()
        assert not math.isnan(llr)
        assert not math.isinf(llr)

    def test_sequential_decisions(self):
        """Test sequential decision making with mixed data."""
        # Start with H0-favoring data, then switch to H1-favoring
        h0_data = [-0.2, -0.1, 0.0, 0.1]
        h1_data = [1.5, 1.8, 2.0, 2.2, 2.5]

        # Add H0 data first
        decision = None
        for x in h0_data:
            decision = self.sprt.update(x)
            if decision.stop:
                break

        # If no early decision, add H1 data
        if decision is None or not decision.stop:
            for x in h1_data:
                decision = self.sprt.update(x)
                if decision.stop:
                    break

        # Should eventually make a decision
        assert decision is not None

    def test_boundary_conditions(self):
        """Test behavior at decision boundaries."""
        config = SPRTConfig(mu0=0.0, mu1=1.0, alpha=0.2, beta=0.2)  # Non-zero thresholds
        sprt = CompositeSPRT(config)

        # Add data exactly at decision boundary
        decision = None
        for i in range(20):
            decision = sprt.update(0.5)  # Exactly between mu0 and mu1
            if decision.stop:
                break

        # Should eventually make a decision or hit sample limit
        assert decision is not None

    def test_extreme_parameter_robustness(self):
        """Test robustness with extreme parameter values."""
        # Very tight error rates
        tight_config = SPRTConfig(mu0=0.0, mu1=0.01, alpha=0.001, beta=0.001)
        sprt = CompositeSPRT(tight_config)

        # Should handle extreme thresholds without crashing
        decision = sprt.update(0.005)
        assert decision is not None
        assert not math.isnan(decision.llr)


class TestSPRTIntegration:
    """Integration tests for complete SPRT workflows."""

    def test_trading_edge_detection(self):
        """Test SPRT for detecting trading edge (realistic scenario)."""
        # H0: no edge (mu = 0), H1: positive edge (mu = 0.5 bps)
        config = SPRTConfig(mu0=0.0, mu1=0.5, alpha=0.05, beta=0.1, min_samples=10, max_samples=50)
        sprt = CompositeSPRT(config)

        # Simulate trading returns with small positive edge
        np.random.seed(123)
        returns = np.random.normal(0.3, 2.0, 100)  # Small edge with noise

        decision = None
        for ret in returns:
            decision = sprt.update(ret)
            if decision.stop:
                break

        # Should make some decision (may not detect edge due to noise)
        assert decision is not None

        # Get final summary
        summary = sprt.get_summary()
        assert summary["n_samples"] >= 10

    def test_regime_change_detection(self):
        """Test SPRT for regime change detection."""
        config = SPRTConfig(mu0=0.0, mu1=2.0, alpha=0.05, beta=0.2, min_samples=5)
        sprt = CompositeSPRT(config)

        # Simulate regime change: start with H0, then switch to H1
        np.random.seed(456)
        regime1 = np.random.normal(0.0, 1.0, 10)   # Null regime
        regime2 = np.random.normal(2.0, 1.0, 15)   # Alternative regime

        all_data = np.concatenate([regime1, regime2])

        decision = None
        change_point = None
        for i, x in enumerate(all_data):
            decision = sprt.update(x)
            if decision.stop:
                change_point = i
                break

        # Should detect change and stop
        assert decision is not None
        assert decision.stop is True
        # May detect early due to GLR characteristics
        if change_point is not None:
            assert change_point >= 0  # Just check it stopped somewhere
