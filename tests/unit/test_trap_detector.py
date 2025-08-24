from __future__ import annotations

import time
import random

import numpy as np
import pytest

from core.scalper.trap import TrapWindow, trap_from_book_deltas, trap_score_from_features
from tests.helpers.trap_sequences import (
    make_neutral_sequence,
    make_fake_wall_sequence,
    make_cancel_then_replenish,
)


@pytest.mark.anyio
def test_trap_edge_empty_returns_zero():
    # Empty window should not raise and should produce zero-ish features
    cancel_ratio, rep_ms, cancel_sum, add_sum = trap_from_book_deltas([])
    assert cancel_sum == 0.0 and add_sum == 0.0
    assert cancel_ratio == 0.0
    # Mapping should handle large rep_ms gracefully
    s = trap_score_from_features(cancel_ratio, rep_ms)
    assert 0.0 <= s <= 1.0
    # Zero activity maps to a tiny value due to latency prior; accept near-zero
    assert s < 0.05


@pytest.mark.anyio
def test_trap_neutral_low_score():
    random.seed(42)
    seq = make_neutral_sequence(n=200)
    cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
    s = trap_score_from_features(cancel_ratio, rep_ms)
    assert 0.0 <= s <= 1.0
    # Neutral should be low-ish given cancel_ratio ~0.5 and large rep_ms
    assert s < 0.35


@pytest.mark.anyio
def test_trap_fake_wall_high_score():
    random.seed(42)
    seq = make_fake_wall_sequence(side="ask", depth=5, n=60, burst_ms=200)
    cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
    s = trap_score_from_features(cancel_ratio, rep_ms)
    # Expect elevated score on burst cancels
    assert s >= 0.55


@pytest.mark.anyio
def test_trap_cancel_then_replenish_high_score():
    random.seed(42)
    # Make cancels dominate and replenish very fast
    seq = make_cancel_then_replenish(side="bid", n_cancel=60, n_add=20, delay_ms=5)
    cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
    s = trap_score_from_features(cancel_ratio, rep_ms)
    assert s >= 0.65


@pytest.mark.anyio
def test_trap_window_z_and_flag_behavior():
    tw = TrapWindow(window_s=2.0, levels=5, history=120)
    # Warm-up with neutral windows to set percentiles
    for _ in range(30):
        seq = make_neutral_sequence(n=50)
        csum = sum(ev.size for ev in seq if ev.action == "cancel")
        asum = sum(ev.size for ev in seq if ev.action == "add")
        cancels = [csum / 5.0] * 5
        adds = [asum / 5.0] * 5
        m = tw.update(cancels, adds, trades_cnt=5, z_threshold=1.64)
        assert np.isfinite(m.trap_z)
    # Now inject a cancel burst
    burst = make_fake_wall_sequence(n=80, burst_ms=150)
    csum = sum(ev.size for ev in burst if ev.action == "cancel")
    asum = sum(ev.size for ev in burst if ev.action == "add")
    cancels = [csum / 5.0] * 5
    adds = [asum / 5.0] * 5
    m = tw.update(cancels, adds, trades_cnt=3, z_threshold=1.2)  # slightly easier threshold for test determinism
    assert m.flag or m.trap_z >= 1.2


@pytest.mark.anyio
def test_trap_perf_budget_p95_under_20ms():
    # Measure scoring on 1k ticks worth of small windows
    tw = TrapWindow(window_s=2.0, levels=5, history=240)
    latencies = []
    for _ in range(50):  # 50 windows ~ 1k events across windows
        seq = make_neutral_sequence(n=20)
        csum = sum(ev.size for ev in seq if ev.action == "cancel")
        asum = sum(ev.size for ev in seq if ev.action == "add")
        cancels = [csum / 5.0] * 5
        adds = [asum / 5.0] * 5
        t0 = time.perf_counter()
        _ = tw.update(cancels, adds, trades_cnt=2)
        latencies.append((time.perf_counter() - t0) * 1000.0)
    p95 = float(np.percentile(np.array(latencies, dtype=float), 95))
    assert p95 < 20.0, f"p95={p95:.2f} ms exceeds 20ms budget"
from core.scalper.trap import BookDelta, trap_from_book_deltas, trap_score_from_features


def test_trap_score_high_on_fast_replenish_and_cancels():
    # Synthetic sequence: rapid cancel followed by add at same price
    evs = [
        BookDelta(ts=0.00, side="bid", price=100.0, size=5.0, action="cancel"),
        BookDelta(ts=0.01, side="bid", price=100.0, size=5.0, action="add"),
        BookDelta(ts=0.02, side="bid", price=100.0, size=5.0, action="cancel"),
        BookDelta(ts=0.03, side="bid", price=100.0, size=5.0, action="add"),
    ]
    cancel_ratio, rep_ms, cancel_sum, add_sum = trap_from_book_deltas(evs, window_s=2.0, levels=5)
    assert cancel_sum > 0 and add_sum > 0
    assert rep_ms < 100.0
    score = trap_score_from_features(cancel_ratio, rep_ms)
    assert 0.0 <= score <= 1.0
    assert score > 0.65


def test_trap_score_low_on_balanced_and_slow_replenish():
    evs = [
        BookDelta(ts=0.00, side="ask", price=101.0, size=3.0, action="add"),
        BookDelta(ts=0.50, side="ask", price=101.0, size=3.0, action="cancel"),
        BookDelta(ts=1.20, side="ask", price=101.0, size=3.0, action="add"),
    ]
    cancel_ratio, rep_ms, cancel_sum, add_sum = trap_from_book_deltas(evs, window_s=2.0, levels=5)
    score = trap_score_from_features(cancel_ratio, rep_ms)
    assert rep_ms > 200.0
    assert score < 0.4
