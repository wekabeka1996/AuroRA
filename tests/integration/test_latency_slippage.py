from __future__ import annotations

from core.aurora.pretrade import gate_latency, gate_slippage, gate_expected_return


def test_latency_guard_blocks_when_p95_exceeds():
    reasons: list[str] = []
    ok = gate_latency(latency_ms=51.0, lmax_ms=50.0, reasons=reasons)
    assert not ok
    assert any("latency_guard_exceeded" in r for r in reasons)


def test_latency_guard_allows_under_threshold():
    reasons: list[str] = []
    ok = gate_latency(latency_ms=30.0, lmax_ms=50.0, reasons=reasons)
    assert ok
    assert reasons == []


def test_slippage_guard_blocks_on_excess():
    reasons: list[str] = []
    # eta=0.3, b=10 -> threshold=3.0, slip=3.5 -> block
    ok = gate_slippage(slip_bps=3.5, b_bps=10.0, eta_fraction_of_b=0.3, reasons=reasons)
    assert not ok
    assert any("slippage_guard_exceeded" in r for r in reasons)


def test_slippage_guard_allows_when_under_eta():
    reasons: list[str] = []
    ok = gate_slippage(slip_bps=2.5, b_bps=10.0, eta_fraction_of_b=0.3, reasons=reasons)
    assert ok
    assert reasons == []


def test_expected_return_gate_positive():
    reasons: list[str] = []
    assert gate_expected_return(e_pi_bps=5.0, pi_min_bps=2.0, reasons=reasons)


def test_expected_return_gate_negative():
    reasons: list[str] = []
    assert not gate_expected_return(e_pi_bps=1.0, pi_min_bps=2.0, reasons=reasons)
    assert "expected_return_below_threshold" in reasons
