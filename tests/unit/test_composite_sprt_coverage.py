"""
Additional tests for core/governance/composite_sprt.py to improve coverage
"""
import pytest
import numpy as np
import time
from unittest.mock import Mock, patch

from core.governance.composite_sprt import (
    CompositeSPRT, AlphaSpendingLedger, AlphaSpendingEntry,
    GaussianKnownVarModel, StudentTModel, SubexponentialModel,
    CompositeHypothesis, HypothesisType, SPRTResult
)


class TestCompositeHypothesis:
    """Test CompositeHypothesis class."""

    def setup_method(self):
        """Setup test fixtures."""
        self.h0_model = GaussianKnownVarModel()
        self.h1_model = GaussianKnownVarModel()
        self.components = [
            (self.h0_model, {'mu': 0.0, 'sigma': 1.0}, 0.5),
            (self.h1_model, {'mu': 1.0, 'sigma': 1.0}, 0.5)
        ]
        self.composite = CompositeHypothesis(self.components)

    def test_composite_hypothesis_creation(self):
        """Test CompositeHypothesis creation."""
        assert len(self.composite.components) == 2
        assert np.allclose(self.composite.weights, [0.5, 0.5])

    def test_composite_hypothesis_log_likelihood_ratio(self):
        """Test LLR calculation."""
        observation = 0.5
        ll = self.composite.log_likelihood(observation)
        assert isinstance(ll, float)
        assert ll != -np.inf

    def test_composite_hypothesis_decision_boundaries(self):
        """Test decision boundary calculations."""
        # Test with extreme observations
        large_positive = self.composite.log_likelihood(5.0)
        large_negative = self.composite.log_likelihood(-5.0)
        
        assert large_positive != -np.inf
        assert large_negative != -np.inf


class TestHypothesisModelsEdgeCases:
    """Test edge cases in hypothesis models."""

    def test_student_t_model_with_insufficient_data(self):
        """Test StudentTModel with insufficient data for statistics."""
        model = StudentTModel()
        
        # Test with empty array
        empty_stats = model.sufficient_statistics(np.array([]))
        assert empty_stats['n'] == 0
        assert empty_stats['sum'] == 0.0
        assert empty_stats['sum_squares'] == 0.0

    def test_subexponential_model_bootstrap_ci(self):
        """Test SubexponentialModel bootstrap confidence interval."""
        model = SubexponentialModel()
        
        # Generate some test data
        np.random.seed(42)
        data = np.random.exponential(1.0, 100)
        
        # Test bootstrap CI with small sample
        lower, upper = model._bootstrap_tail_index_ci(data, k=5, n_bootstrap=10)
        assert isinstance(lower, float)
        assert isinstance(upper, float)
        assert lower <= upper

    def test_subexponential_model_insufficient_data(self):
        """Test SubexponentialModel with insufficient data."""
        model = SubexponentialModel()
        
        # Test with very small dataset
        small_data = np.array([1.0, 2.0])
        lower, upper = model._bootstrap_tail_index_ci(small_data, k=5, n_bootstrap=10)
        # Should return default tail index
        assert lower == model.tail_index
        assert upper == model.tail_index


class TestCompositeSPRTEdgeCases:
    """Test edge cases in CompositeSPRT."""

    def setup_method(self):
        """Setup test fixtures."""
        self.h0_model = GaussianKnownVarModel()
        self.h1_model = GaussianKnownVarModel()
        self.sprt = CompositeSPRT(alpha=0.05, beta=0.20)

    def test_composite_sprt_empty_observations(self):
        """Test CompositeSPRT with no observations."""
        assert self.sprt.n_samples == 0
        assert self.sprt.log_lr == 0.0
        assert len(self.sprt.observations) == 0

    def test_composite_sprt_single_observation(self):
        """Test CompositeSPRT with single observation."""
        result = self.sprt.update(
            observation=1.0,
            model_h0=self.h0_model,
            model_h1=self.h1_model
        )
        assert result.n_samples == 1
        assert isinstance(result.log_likelihood_ratio, float)

    def test_composite_sprt_extreme_observations(self):
        """Test CompositeSPRT with extreme observations."""
        # Test with very large positive value
        result1 = self.sprt.update(
            observation=100.0,
            model_h0=self.h0_model,
            model_h1=self.h1_model
        )
        assert result1.n_samples == 1

        # Reset and test with very large negative value
        self.sprt.reset()
        result2 = self.sprt.update(
            observation=-100.0,
            model_h0=self.h0_model,
            model_h1=self.h1_model
        )
        assert result2.n_samples == 1

    def test_composite_sprt_reset(self):
        """Test CompositeSPRT reset functionality."""
        self.sprt.update(1.0, self.h0_model, self.h1_model)
        self.sprt.update(2.0, self.h0_model, self.h1_model)
        assert self.sprt.n_samples == 2

        self.sprt.reset()
        assert self.sprt.n_samples == 0
        assert self.sprt.log_lr == 0.0
        assert len(self.sprt.observations) == 0

    def test_composite_sprt_with_ledger(self):
        """Test CompositeSPRT with alpha spending ledger."""
        ledger = AlphaSpendingLedger(total_alpha=0.1)
        sprt = CompositeSPRT(alpha_ledger=ledger)

        result = self.sprt.update(1.0, self.h0_model, self.h1_model)
        assert result.alpha_spent >= 0.0


class TestSPRTResult:
    """Test SPRTResult dataclass."""

    def test_sprt_result_creation(self):
        """Test SPRTResult creation."""
        result = SPRTResult(
            decision='accept_h1',
            log_likelihood_ratio=2.5,
            n_samples=100,
            p_value=0.01,
            confidence=0.95,
            boundaries={'A': 2.0, 'B': -2.0},
            test_statistic=2.5,
            alpha_spent=0.05
        )
        
        assert result.decision == 'accept_h1'
        assert result.log_likelihood_ratio == 2.5
        assert result.n_samples == 100

    def test_sprt_result_with_none_values(self):
        """Test SPRTResult with None values."""
        result = SPRTResult(
            decision=None,
            log_likelihood_ratio=0.0,
            n_samples=0,
            p_value=1.0,
            confidence=0.0,
            boundaries={},
            test_statistic=0.0,
            alpha_spent=0.0
        )
        
        assert result.decision is None
        assert result.log_likelihood_ratio == 0.0
        assert result.n_samples == 0


class TestSubexponentialModelEdgeCases:
    """Tests for SubexponentialModel edge cases"""

    def test_subexponential_model_empty_observations(self):
        """Test SubexponentialModel with empty observations."""
        model = SubexponentialModel()
        stats = model.sufficient_statistics(np.array([]))
        assert stats['n'] == 0

    def test_subexponential_model_insufficient_positive_data(self):
        """Test SubexponentialModel with insufficient positive data for POT."""
        model = SubexponentialModel()
        # Create data with less than 10 positive observations
        data = np.array([1.0, 2.0, 3.0, 4.0, 5.0])  # Only 5 positive values
        stats = model.sufficient_statistics(data)
        assert stats['n'] == 5
        assert 'tail_index' in stats
        assert 'pot_threshold' in stats

    def test_subexponential_model_bootstrap_empty_tail_indices(self):
        """Test bootstrap CI when no tail indices are generated."""
        model = SubexponentialModel()
        # This should trigger the case where tail_indices is empty
        lower, upper = model._bootstrap_tail_index_ci(np.array([1.0]), k=1, n_bootstrap=1)
        assert lower == model.tail_index
        assert upper == model.tail_index

class TestAlphaSpendingLedgerEdgeCases:
    """Tests for AlphaSpendingLedger edge cases"""

    def test_unknown_policy_warning(self):
        """Test unknown policy triggers warning and defaults to pocock."""
        with patch('core.governance.composite_sprt.logger') as mock_logger:
            ledger = AlphaSpendingLedger(total_alpha=0.1, policy="unknown")
            mock_logger.warning.assert_called_once()
            # Should default to pocock
            assert ledger._get_alpha_spending_function() == ledger._pocock_spending

    def test_bh_fdr_policy_calculation(self):
        """Test BH-FDR policy calculation."""
        ledger = AlphaSpendingLedger(total_alpha=0.1, policy="bh-fdr")
        ledger.set_expected_tests(5)
        
        # Test spending calculation for different test indices
        alpha_for_test_0 = ledger._bh_fdr_spending(0, 5)
        alpha_for_test_2 = ledger._bh_fdr_spending(2, 5)
        
        assert alpha_for_test_0 == 0.1 * 1 / 5  # (t=1)/total_tests
        assert alpha_for_test_2 == 0.1 * 3 / 5  # (t=3)/total_tests

class TestCompositeSPRTErrorHandling:
    """Tests for CompositeSPRT error handling"""

    def test_composite_sprt_with_invalid_model_params(self):
        """Test CompositeSPRT with models that might fail."""
        h0_model = GaussianKnownVarModel()
        h1_model = GaussianKnownVarModel()
        sprt = CompositeSPRT()
        
        # Test with missing parameters (should use defaults)
        result = sprt.update(1.0, h0_model, h1_model)
        assert isinstance(result, SPRTResult)

    def test_composite_sprt_boundary_decisions(self):
        """Test CompositeSPRT decision boundaries."""
        h0_model = GaussianKnownVarModel()
        h1_model = GaussianKnownVarModel()
        sprt = CompositeSPRT(alpha=0.05, beta=0.20)
        
        # Add observations that should trigger different decisions
        # This is more of an integration test
        for i in range(50):
            result = sprt.update(float(i), h0_model, h1_model)
            if result.decision is not None:
                break
        
        # At minimum we should get some result
        assert result is not None

class TestCompositeHypothesisMixture:
    """Tests for CompositeHypothesis mixture components"""

    def test_composite_hypothesis_single_component(self):
        """Test CompositeHypothesis with single component."""
        model = GaussianKnownVarModel()
        components = [(model, {'mu': 0.0, 'sigma': 1.0}, 1.0)]
        composite = CompositeHypothesis(components)
        
        assert len(composite.components) == 1
        assert np.allclose(composite.weights, [1.0])

    def test_composite_hypothesis_multiple_components(self):
        """Test CompositeHypothesis with multiple components."""
        model1 = GaussianKnownVarModel()
        model2 = StudentTModel()
        components = [
            (model1, {'mu': 0.0, 'sigma': 1.0}, 0.3),
            (model2, {'mu': 0.0, 'nu': 5.0, 'scale': 1.0}, 0.7)
        ]
        composite = CompositeHypothesis(components)
        
        assert len(composite.components) == 2
        assert np.allclose(composite.weights, [0.3, 0.7])

    def test_composite_hypothesis_log_likelihood_inf(self):
        """Test CompositeHypothesis when all components return -inf."""
        # Create a scenario where all components might return -inf
        model = GaussianKnownVarModel()
        components = [(model, {'mu': 0.0, 'sigma': 1.0}, 1.0)]
        composite = CompositeHypothesis(components)
        
        # Test with extreme value that might cause issues
        ll = composite.log_likelihood(1e10)
        assert isinstance(ll, float)  # Should handle gracefully

    def test_composite_hypothesis_empty_components(self):
        """Test CompositeHypothesis with empty components list."""
        composite = CompositeHypothesis([])
        
        # Should return -inf for empty components
        ll = composite.log_likelihood(1.0)
        assert ll == -np.inf

class TestSubexponentialModelPOT:
    """Tests for SubexponentialModel POT (Peak-Over-Threshold) functionality"""

    def test_subexponential_model_with_sufficient_data(self):
        """Test SubexponentialModel with sufficient data for POT analysis."""
        model = SubexponentialModel()
        # Create data with more than 10 positive observations
        np.random.seed(42)
        data = np.random.exponential(1.0, 50)  # 50 positive observations
        stats = model.sufficient_statistics(data)
        
        assert stats['n'] == 50
        assert 'tail_index' in stats
        assert 'pot_threshold' in stats
        assert 'n_excesses' in stats

    def test_subexponential_model_hill_estimation(self):
        """Test Hill estimation in SubexponentialModel."""
        model = SubexponentialModel()
        # Create data that will trigger Hill estimation
        excesses = np.array([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])  # 8 excesses
        k = max(1, len(excesses) // 4)  # k = 2
        
        # This should trigger the Hill estimation path
        lower, upper = model._bootstrap_tail_index_ci(excesses, k, n_bootstrap=10)
        assert isinstance(lower, float)
        assert isinstance(upper, float)

class TestAlphaSpendingPoliciesEdgeCases:
    """Tests for alpha spending policy edge cases"""

    def test_obrien_fleming_edge_cases(self):
        """Test O'Brien-Fleming policy with edge cases."""
        ledger = AlphaSpendingLedger(total_alpha=0.1, policy="obf")
        
        # Test with invalid parameters
        alpha_invalid_tests = ledger._obrien_fleming_spending(0, 0)  # total_tests = 0
        assert alpha_invalid_tests == 0.1
        
        alpha_invalid_idx = ledger._obrien_fleming_spending(-1, 5)  # test_idx = -1
        assert alpha_invalid_idx == 0.1

    def test_pocock_edge_cases(self):
        """Test Pocock policy with edge cases."""
        ledger = AlphaSpendingLedger(total_alpha=0.1, policy="pocock")
        
        # Test with zero total tests
        alpha_zero_tests = ledger._pocock_spending(0, 0)
        assert alpha_zero_tests == 0.1

class TestCompositeSPRTComplexScenarios:
    """Tests for complex CompositeSPRT scenarios"""

    def test_composite_sprt_with_composite_hypothesis(self):
        """Test CompositeSPRT with CompositeHypothesis models."""
        # Create composite hypotheses
        h0_model = GaussianKnownVarModel()
        h1_model = GaussianKnownVarModel()
        h0_components = [(h0_model, {'mu': 0.0, 'sigma': 1.0}, 1.0)]
        h1_components = [(h1_model, {'mu': 1.0, 'sigma': 1.0}, 1.0)]
        
        h0_composite = CompositeHypothesis(h0_components)
        h1_composite = CompositeHypothesis(h1_components)
        
        sprt = CompositeSPRT()
        result = sprt.update(0.5, h0_composite, h1_composite)
        assert isinstance(result, SPRTResult)

    def test_composite_sprt_multiple_updates(self):
        """Test CompositeSPRT with multiple sequential updates."""
        h0_model = GaussianKnownVarModel()
        h1_model = GaussianKnownVarModel()
        sprt = CompositeSPRT()
        
        # Add multiple observations
        observations = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0]
        for obs in observations:
            result = sprt.update(obs, h0_model, h1_model)
            assert isinstance(result, SPRTResult)
        
        assert sprt.n_samples == len(observations)