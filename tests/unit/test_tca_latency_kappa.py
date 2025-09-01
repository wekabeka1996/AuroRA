import pytest

tca = pytest.importorskip("core.tca.latency", reason="tca latency missing")


def test_kappa_effects_basic():
    # Ensure kappa multiplies latency cost linearly
    g = tca.compute_latency_penalty
    assert pytest.approx(g(0, 0)) == 0
    v1 = g(1.0, 10.0)
    v2 = g(2.0, 10.0)
    assert v2 > v1

