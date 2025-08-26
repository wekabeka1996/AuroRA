from __future__ import annotations

from aurora.governance import Governance


def test_spread_latency_volatility_guards():
    gov = Governance({"gates": {"spread_bps_limit": 50, "latency_ms_limit": 100, "vol_guard_std_bps": 200}})
    # spread
    r = gov.approve({"symbol": "BTCUSDT"}, {"spread_bps": 80})
    assert r["allow"] is False and r["code"] == "SPREAD_GUARD_TRIP"
    # latency
    r = gov.approve({"symbol": "BTCUSDT"}, {"spread_bps": 10, "latency_ms": 150})
    assert r["allow"] is False and r["code"] == "LATENCY_GUARD_TRIP"
    # volatility
    r = gov.approve({"symbol": "BTCUSDT"}, {"spread_bps": 10, "latency_ms": 50, "vol_std_bps": 500})
    assert r["allow"] is False and r["code"] == "VOLATILITY_GUARD_TRIP"


def test_dd_cvar_and_pos_limit():
    gov = Governance({"gates": {"daily_dd_limit_pct": 5.0, "cvar_limit": 0.0, "max_concurrent_positions": 1}})
    # daily dd
    r = gov.approve({"symbol": "BTCUSDT"}, {"pnl_today_pct": -6.0})
    assert r["allow"] is False and r["code"] == "RISK.DENY.DRAWDOWN"
    # cvar
    r = gov.approve({"symbol": "BTCUSDT"}, {"pnl_today_pct": 0.0, "cvar_hist": -1.0})
    assert r["allow"] is False and r["code"] == "RISK.DENY.CVAR"
    # pos limit
    r = gov.approve({"symbol": "BTCUSDT"}, {"open_positions": 1})
    assert r["allow"] is False and r["code"] == "RISK.DENY.POS_LIMIT"


def test_killswitch_reject_storm():
    gov = Governance({"gates": {"reject_storm_pct": 0.5, "reject_storm_cooldown_s": 1}})
    # First call with high reject rate should activate halt
    r1 = gov.approve({"symbol": "BTCUSDT"}, {"recent_stats": {"rejects": 10, "total": 10}})
    assert r1["allow"] is False and r1["code"] == "AURORA.HALT"
    # subsequent call remains halted
    r2 = gov.approve({"symbol": "BTCUSDT"}, {"recent_stats": {"rejects": 0, "total": 1}})
    assert r2["allow"] is False and r2["code"] == "AURORA.HALT"
    # resume clears
    gov.resume()
    r3 = gov.approve({"symbol": "BTCUSDT"}, {"recent_stats": {"rejects": 0, "total": 1}})
    assert r3["allow"] is True
