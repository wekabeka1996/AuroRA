"""Test for SPRT stability with constant observations and p_value range."""

import pytest
from core.governance.sprt_glr import CompositeSPRT, SPRTConfig, SPRTOutcome


def test_constant_stream_stability():
    """Test that constant observation stream doesn't crash and p_value is in [0,1]."""
    config = SPRTConfig(mu0=0.0, mu1=0.1, alpha=0.05, beta=0.2, min_samples=3, max_samples=10)
    sprt = CompositeSPRT(config)
    
    # Feed constant observations (should have low variance)
    constant_value = 0.05  # neutral between mu0 and mu1
    
    for i in range(10):  # force max_samples
        result = sprt.update(constant_value)
        
        # Should not crash
        assert isinstance(result.llr, float)
        assert isinstance(result.confidence, float)
        assert result.n_samples == i + 1
        
        # If stopped, p_value should be valid
        if result.stop and result.p_value is not None:
            assert 0.0 <= result.p_value <= 1.0
    
    # Final result should be stopped (due to max_samples)
    assert result.stop
    assert result.outcome == SPRTOutcome.ACCEPT_H0  # default for timeout
    
    # p_value should be computed for final decision
    if result.p_value is not None:
        assert 0.0 <= result.p_value <= 1.0


def test_factory_parameters():
    """Test that factory functions accept all parameters correctly."""
    from core.governance.sprt_glr import create_sprt_pocock
    
    sprt = create_sprt_pocock(
        alpha=0.01, 
        mu0=-0.1, 
        mu1=0.2, 
        beta=0.1, 
        min_samples=3, 
        max_samples=20
    )
    
    # Check configuration was applied
    assert sprt.config.alpha == 0.01
    assert sprt.config.mu0 == -0.1
    assert sprt.config.mu1 == 0.2
    assert sprt.config.beta == 0.1
    assert sprt.config.min_samples == 3
    assert sprt.config.max_samples == 20