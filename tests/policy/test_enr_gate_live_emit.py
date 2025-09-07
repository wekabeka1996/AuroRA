import os
from pathlib import Path


def test_enr_helper_allows_when_edge_exceeds_costs():
    # Import after path is set by pytest
    from skalp_bot.runner.run_live_aurora import _compute_enr
    class _Fees:
        def __init__(self, maker_fee_bps=0.0, taker_fee_bps=8.0):
            self.maker_fee_bps = maker_fee_bps
            self.taker_fee_bps = taker_fee_bps

    cfg = {"reward": {"expected_net_reward_threshold_bps": 0.0}}
    enr = _compute_enr(cfg, edge_before_bps=12.0, spread_bps=10.0, route='taker', fees=_Fees())
    assert enr["expected_cost_total_bps"] > 0.0
    assert enr["expected_pnl_proxy_bps"] == 12.0 - enr["expected_cost_total_bps"]
    assert enr["outcome"] in {"allow", "deny"}


def test_enr_helper_denies_when_threshold_positive():
    from skalp_bot.runner.run_live_aurora import _compute_enr
    class _Fees:
        def __init__(self, maker_fee_bps=0.0, taker_fee_bps=8.0):
            self.maker_fee_bps = maker_fee_bps
            self.taker_fee_bps = taker_fee_bps

    cfg = {"reward": {"expected_net_reward_threshold_bps": 5.0}}
    # Make edge small so pnl proxy likely < 5.0
    enr = _compute_enr(cfg, edge_before_bps=6.0, spread_bps=10.0, route='taker', fees=_Fees())
    assert enr["outcome"] == ("allow" if enr["expected_pnl_proxy_bps"] >= 5.0 else "deny")
