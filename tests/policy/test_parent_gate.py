# -*- coding: utf-8 -*-
import time
import pytest

from core.policy.gates.parent_gate import ParentGate

CFG = {
    "enabled": True,
    "parent": "SOLUSDT",
    "child": "SOONUSDT",
    "lookback_s": 120,
    "z_threshold": 0.75,
    "align_sign": True,
    "max_spread_bps": 50,
    "cooloff_s": 30,
}


def mk_gate():
    return ParentGate(CFG)


def feed_parent_prices(g: ParentGate, prices):
    # prices: list of (ts, mid) -> compute returns from successive mids
    prev = None
    for ts, mid in prices:
        if prev is None:
            ret = 0.0
        else:
            ret = (mid - prev) / (prev or 1e-9)
        g.record_parent_return(ret, ts)
        prev = mid


def test_deny_when_parent_weak():
    g = mk_gate()
    now = time.time()
    feed_parent_prices(g, [
        (now - 120, 100.0), (now - 60, 100.2), (now - 1, 100.21)
    ])
    out = g.evaluate(parent_ret=0.0001, child_direction=1, child_spread_bps=10)
    assert out["outcome"] == "deny"
    assert out["reason"] == "parent_weak"


def test_deny_when_misaligned_direction():
    g = mk_gate()
    now = time.time()
    # make prior returns small, then a strong up move to ensure high z
    feed_parent_prices(g, [
        (now - 120, 100.0), (now - 60, 100.05), (now - 10, 100.06), (now - 1, 110.0)
    ])
    # parent strong up, child sell -> misaligned
    out = g.evaluate(parent_ret=(110.0 - 100.06) / 100.06, child_direction=-1, child_spread_bps=10)
    assert out["outcome"] == "deny"
    assert out["reason"] == "parent_misaligned"


def test_deny_when_child_spread_wide():
    g = mk_gate()
    now = time.time()
    feed_parent_prices(g, [
        (now - 120, 100.0), (now - 60, 100.05), (now - 1, 110.0)
    ])
    out = g.evaluate(parent_ret=(110.0 - 100.05) / 100.05, child_direction=1, child_spread_bps=100)
    assert out["outcome"] == "deny"
    assert out["reason"] == "child_spread"


def test_allow_when_all_good():
    g = mk_gate()
    now = time.time()
    # create strong parent up move with prior low-variance history
    feed_parent_prices(g, [
        (now - 120, 100.0), (now - 60, 100.02), (now - 10, 100.03), (now - 1, 110.0)
    ])
    out = g.evaluate(parent_ret=(110.0 - 100.03) / 100.03, child_direction=1, child_spread_bps=10)
    assert out["outcome"] == "allow"
    assert out["aligned"] is True
    assert out["z"] >= g.z_threshold
