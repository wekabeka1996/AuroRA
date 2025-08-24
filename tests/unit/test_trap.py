from __future__ import annotations

from core.scalper.trap import TrapWindow


def test_trap_flags_on_high_cancel_low_replenish():
    tw = TrapWindow(window_s=2.0, levels=5)
    # Warmup with benign values
    for _ in range(20):
        m = tw.update([0, 0, 0, 0, 0], [1, 1, 1, 1, 1], trades_cnt=10, z_threshold=10.0)
        assert m.flag is False
    # Now strong cancels and few adds, few trades
    m2 = tw.update([10, 8, 6, 4, 2], [0, 0, 0, 0, 0], trades_cnt=1, z_threshold=1.0)
    assert m2.flag is True, m2


def test_trap_normal_market_is_ok():
    tw = TrapWindow(window_s=2.0, levels=5)
    for _ in range(30):
        m = tw.update([1, 1, 1, 1, 1], [1, 1, 1, 1, 1], trades_cnt=20, z_threshold=2.0)
        assert m.flag is False


def test_trap_conflict_rule_blocks():
    tw = TrapWindow(window_s=2.0, levels=5)
    # Warmup
    for _ in range(10):
        tw.update([1, 1, 1, 1, 1], [1, 1, 1, 1, 1], trades_cnt=10)
    # Now conflict between OBI and TFI and high cancel rate (above rolling p90)
    m = tw.update([10, 10, 10, 10, 10], [0, 0, 0, 0, 0], trades_cnt=5, obi_sign=1, tfi_sign=-1)
    assert m.flag is True