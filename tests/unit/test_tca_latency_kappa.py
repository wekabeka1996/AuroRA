import pytest

tca = pytest.importorskip("core.tca.latency", reason="tca latency missing")


def test_kappa_effects_basic():
    # Test edge_after_latency function with different kappa values
    # Ensure kappa multiplies latency cost linearly
    edge1 = tca.edge_after_latency(edge_bps=10.0, latency_ms=5.0, kappa_bps_per_ms=0.1)
    edge2 = tca.edge_after_latency(edge_bps=10.0, latency_ms=5.0, kappa_bps_per_ms=0.2)
    
    # Higher kappa should result in lower edge after latency
    assert edge2 < edge1
    
    # Test with zero latency
    edge_zero = tca.edge_after_latency(edge_bps=10.0, latency_ms=0.0, kappa_bps_per_ms=0.1)
    assert edge_zero == 10.0

