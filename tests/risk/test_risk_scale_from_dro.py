import math
import pytest

from living_latent.execution.gating import risk_scale_from_dro, apply_risk_scale


def test_risk_scale_from_dro_monotonic():
    ks = [0.0, 0.001, 0.005, 0.01, 0.02]
    vals = [risk_scale_from_dro(p, k=10.0, cap=0.5) for p in ks]
    # Non-increasing sequence
    assert all(vals[i] >= vals[i+1] - 1e-12 for i in range(len(vals)-1))
    # First near 1
    assert 0.95 <= vals[0] <= 1.0


def test_risk_scale_from_dro_cap_and_floor():
    # Large penalty drives raw scale below cap -> clamp
    s = risk_scale_from_dro(0.5, k=10.0, cap=0.5)
    assert math.isclose(s, 0.5, rel_tol=1e-9)
    # Negative / nan penalty -> neutral
    assert risk_scale_from_dro(-0.1) == 1.0
    assert risk_scale_from_dro(float('nan')) == 1.0


def test_apply_risk_scale_integration():
    base_notional = 100.0
    penalties = [0.0, 0.01, 0.05, 0.10]
    prev = None
    notional = base_notional
    for p in penalties:
        rs = risk_scale_from_dro(p, k=8.0, cap=0.4)
        notional = apply_risk_scale(base_notional, rs)
        if prev is not None:
            assert notional <= prev + 1e-9  # monotone non-increasing
        prev = notional
    # Floor respected
    assert notional >= base_notional * 0.4 - 1e-9
