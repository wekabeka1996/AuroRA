"""Quick smoke test for CompositeSPRT compatibility layer."""

from core.governance.sprt_glr import (
    AlphaSpendingPolicy,
    CompositeSPRT,
    SPRTConfig,
    SPRTOutcome,
    SPRTResult,
    create_sprt_bh_fdr,
    create_sprt_obf,
    create_sprt_pocock,
)


def test_compat_layer_imports():
    """Test that all compatibility imports work."""
    # Test enum values exist
    assert SPRTOutcome.TIMEOUT.value == "timeout"
    assert AlphaSpendingPolicy.POCOCK.value == "pocock"

    # Test alias works (check it's the same class)
    from core.governance.sprt_glr import SPRTDecision
    assert SPRTResult is SPRTDecision

def test_factory_functions():
    """Test factory functions create valid SPRT instances."""
    sprt1 = create_sprt_pocock(alpha=0.05, mu0=0.0, mu1=0.2)
    sprt2 = create_sprt_obf(alpha=0.1, mu0=-0.1, mu1=0.1)
    sprt3 = create_sprt_bh_fdr(alpha=0.01, mu0=0.0, mu1=0.5)

    assert isinstance(sprt1, CompositeSPRT)
    assert isinstance(sprt2, CompositeSPRT)
    assert isinstance(sprt3, CompositeSPRT)

    # Test configuration
    assert sprt1.config.alpha == 0.05
    assert sprt1.config.mu0 == 0.0
    assert sprt1.config.mu1 == 0.2

def test_sprt_result_alias():
    """Test SPRTResult alias works with type hints."""
    sprt = create_sprt_pocock(alpha=0.05, mu0=0.0, mu1=0.2)

    # Process some observations
    for i in range(7):
        result: SPRTResult = sprt.update(0.1)  # type: ignore[assignment]
        assert result.outcome in (SPRTOutcome.CONTINUE, SPRTOutcome.ACCEPT_H0, SPRTOutcome.ACCEPT_H1)
        assert isinstance(result.llr, float)
        assert isinstance(result.confidence, float)
        assert result.n_samples == i + 1

def test_timeout_enum_available():
    """Test TIMEOUT enum is available but not used in current logic."""
    # TIMEOUT exists for imports but current max_samples logic uses ACCEPT_H0
    assert SPRTOutcome.TIMEOUT.value == "timeout"

    # Verify max_samples still forces ACCEPT_H0 (не TIMEOUT)
    sprt = CompositeSPRT(SPRTConfig(mu0=0.0, mu1=0.1, alpha=0.05, max_samples=5))

    # Force timeout by reaching max_samples without decision
    for _ in range(5):
        result = sprt.update(0.05)  # neutral observation

    # Should still be ACCEPT_H0, not TIMEOUT (preserving existing behavior)
    assert result.outcome == SPRTOutcome.ACCEPT_H0
    assert result.stop is True

def test_all_exports_available():
    """Test that __all__ exports work."""
    from core.governance.sprt_glr import (
        AlphaSpendingPolicy,
        CompositeSPRT,
        SPRTConfig,
        SPRTDecision,
        SPRTOutcome,
        SPRTResult,
        SPRTState,
        create_sprt_bh_fdr,
        create_sprt_obf,
        create_sprt_pocock,
    )

    # All imports successful
    assert all([
        SPRTConfig, SPRTState, SPRTDecision, SPRTOutcome, CompositeSPRT,
        SPRTResult, AlphaSpendingPolicy,
        create_sprt_pocock, create_sprt_obf, create_sprt_bh_fdr
    ])
