from __future__ import annotations

import math
import pytest

from core.tca.fill_prob import p_fill_at_T


@pytest.mark.parametrize("T1,T2", [(10, 50), (50, 200), (200, 1000)])
def test_pfill_increases_with_time(T1, T2):
    p1 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=0.0, spread_bps=10, T_ms=T1)
    p2 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=0.0, spread_bps=10, T_ms=T2)
    assert p2 > p1


@pytest.mark.parametrize("o1,o2", [(-0.5, 0.0), (0.0, 0.5), (-0.8, 0.8)])
def test_pfill_increases_with_obi(o1, o2):
    p1 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=o1, spread_bps=10, T_ms=200)
    p2 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=o2, spread_bps=10, T_ms=200)
    assert p2 > p1


@pytest.mark.parametrize("q1,q2", [(0.0, 1.0), (1.0, 5.0), (2.0, 20.0)])
def test_pfill_decreases_with_queue_fraction(q1, q2):
    # depth_at_price fixed at 10 => q = queue_pos/depth
    p1 = p_fill_at_T("BUY", queue_pos=q1, depth_at_price=10, obi=0.0, spread_bps=10, T_ms=200)
    p2 = p_fill_at_T("BUY", queue_pos=q2, depth_at_price=10, obi=0.0, spread_bps=10, T_ms=200)
    assert p2 < p1


@pytest.mark.parametrize("s1,s2", [(5, 20), (20, 40), (10, 80)])
def test_pfill_decreases_with_spread(s1, s2):
    p1 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=0.0, spread_bps=s1, T_ms=200)
    p2 = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=0.0, spread_bps=s2, T_ms=200)
    assert p2 < p1


def test_bounds_with_eps():
    p = p_fill_at_T("BUY", queue_pos=0, depth_at_price=0, obi=0.0, spread_bps=0, T_ms=0)
    assert 1e-4 <= p <= 1.0 - 1e-4


def test_side_symmetry():
    a = p_fill_at_T("BUY", queue_pos=1, depth_at_price=10, obi=0.2, spread_bps=10, T_ms=200)
    b = p_fill_at_T("SELL", queue_pos=1, depth_at_price=10, obi=0.2, spread_bps=10, T_ms=200)
    assert abs(a - b) < 1e-12
