import pytest

sla = pytest.importorskip("core.tca.latency", reason="tca latency missing")


def test_sla_gate_boundaries():
    gate = sla.SLAGate(max_latency_ms=100.0)
    
    # Test within limits
    result = gate.gate(edge_bps=10.0, latency_ms=50.0)
    assert result.allow is True
    assert result.reason == "OK"
    
    # Test latency breach
    result = gate.gate(edge_bps=10.0, latency_ms=150.0)
    assert result.allow is False
    assert "latency" in result.reason.lower()
    
    # Test edge floor breach
    result = gate.gate(edge_bps=1.0, latency_ms=50.0)
    assert result.allow is False
    assert "edge" in result.reason.lower()

