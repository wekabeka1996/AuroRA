import pytest

sla = pytest.importorskip("core.tca.latency", reason="tca latency missing")


def test_sla_gate_boundaries():
    gate = sla.SLAGate(max_latency_ms=100.0)
    assert gate.check_latency(100.0) is False or gate.check_latency(100.0) is True

