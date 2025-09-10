import time

import pytest

from core.ingestion.sync_clock import ManualClock, RealTimeClock, ReplayClock


def test_manual_clock_basics():
    c = ManualClock(start_wall_ns=0)
    assert c.now_ns() == 0

    c.advance_ns(10)
    assert c.now_ns() == 10

    # sleep_until_wall_ns moves internal time forward
    c.sleep_until_wall_ns(100)
    assert c.now_ns() == 100

    # event sleep aliases to wall in ManualClock
    c.sleep_until_event_ts_ns(150)
    assert c.now_ns() == 150

    # cannot go backwards via advance
    with pytest.raises(ValueError):
        c.advance_ns(-1)


def test_realtime_clock_monotonic_and_non_blocking_negative_sleep():
    c = RealTimeClock()
    a = c.now_ns()
    b = c.now_ns()
    assert b >= a  # monotonic perf counter

    # negative remaining time should not sleep or raise
    start = time.perf_counter_ns()
    c.sleep_until_wall_ns(c.now_ns() - 1)
    end = time.perf_counter_ns()
    # sanity: call returned quickly (<< 10ms)
    assert (end - start) < 10_000_000


def test_replay_clock_anti_backtracking_and_speed_param():
    # invalid speed
    with pytest.raises(ValueError):
        ReplayClock(speed=0)

    # basic anti-backtracking: decreasing event ts triggers error
    rc = ReplayClock(speed=1.0, drift_tolerance_ns=5_000_000, allow_reanchor=False)
    now = time.perf_counter_ns()

    # anchor explicitly near 'now' so that sleep is ~0
    rc.start(event_anchor_ts_ns=1_000_000_000)  # 1s in ns (arbitrary epoch ref)

    # forward event (no error)
    rc.sleep_until_event_ts_ns(1_000_000_100)

    # backward event -> should raise
    with pytest.raises(ValueError):
        rc.sleep_until_event_ts_ns(1_000_000_050)


def test_replay_clock_reanchor_on_drift():
    """Test re-anchoring when drift exceeds tolerance."""
    rc = ReplayClock(speed=1.0, drift_tolerance_ns=10_000_000, allow_reanchor=True)  # 10ms tolerance

    # Start with anchor
    rc.start(event_anchor_ts_ns=1_000_000_000)

    # Simulate drift by manually setting wall time ahead
    original_now = rc.now_ns()
    rc._wall_anchor_ns = original_now - 15_000_000  # 15ms drift (exceeds 10ms tolerance)

    # Next event should trigger re-anchoring
    target_before = rc._target_wall_ns_for_event(1_000_000_100)

    # After re-anchoring, target should align with current wall time
    current_now = rc.now_ns()
    # The target should be close to current wall time (within small tolerance)
    assert abs(target_before - current_now) < 1_000_000  # within 1ms
