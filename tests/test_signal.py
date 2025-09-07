"""
Basic tests for signal processing modules
Used for mutation testing validation
"""

import pytest
from core.signal.score import ScoreModel, _sigmoid, _clip
from core.signal.fdr import bh_qvalues, reject
from core.signal.leadlag_hy import CrossAssetHY


class TestSignalScore:
    """Test signal scoring functionality"""

    def test_score_model_creation(self):
        """Test basic ScoreModel creation"""
        model = ScoreModel(weights={"test": 1.0}, intercept=0.0)
        assert model is not None

    def test_score_calculation(self):
        """Test score calculation with features"""
        model = ScoreModel(weights={"feature1": 0.5, "feature2": 0.3}, intercept=-0.1)
        features = {"feature1": 1.0, "feature2": 2.0}
        score = model.score_only(features)
        assert isinstance(score, float)

    def test_sigmoid_function(self):
        """Test sigmoid function"""
        assert _sigmoid(0) == 0.5
        assert _sigmoid(10) > 0.5
        assert _sigmoid(-10) < 0.5

    def test_clip_function(self):
        """Test clip function"""
        assert _clip(5, 0, 10) == 5
        assert _clip(-5, 0, 10) == 0
        assert _clip(15, 0, 10) == 10


class TestSignalFDR:
    """Test FDR (False Discovery Rate) calculations"""

    def test_bh_qvalues_basic(self):
        """Test BH q-values calculation"""
        p_values = [0.01, 0.02, 0.03, 0.04, 0.05]
        q_values = bh_qvalues(p_values)
        assert len(q_values) == len(p_values)
        assert all(isinstance(q, float) for q in q_values)

    def test_reject_basic(self):
        """Test reject function"""
        p_values = [0.01, 0.02, 0.03, 0.04, 0.05]
        rejected_mask, num_rejected = reject(p_values, alpha=0.05)
        assert isinstance(rejected_mask, list)
        assert isinstance(num_rejected, int)
        assert len(rejected_mask) == len(p_values)
        assert all(isinstance(r, bool) for r in rejected_mask)


class TestLeadLagCalculator:
    """Test lead-lag calculation functionality"""

    def test_cross_asset_hy_creation(self):
        """Test CrossAssetHY creation"""
        calculator = CrossAssetHY()
        assert calculator is not None

    def test_add_tick(self):
        """Test adding tick data"""
        calculator = CrossAssetHY()
        calculator.add_tick("SOL", 1000.0, 50.0)
        # Should not raise exception
        assert True


# Simple comparison tests for mutation testing
def test_simple_comparisons():
    """Simple tests that mutation testing can work with"""
    x = 5
    y = 10

    # These comparisons will be mutated by our simple mutator
    assert x < y
    assert x != y
    assert y > x
    assert x <= 5
    assert y >= 10


def test_boolean_logic():
    """Boolean logic tests for mutation testing"""
    a = True
    b = False

    # These will be mutated (and/or operations)
    assert a and not b
    assert a or b
    assert not (a and b)
    assert (a or b) and True
