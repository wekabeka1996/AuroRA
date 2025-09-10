from core.config_loader import RewardCfg
from core.reward_manager import PositionState, RewardManager


def _st(
    side: str = "LONG",
    entry: float = 100.0,
    price: float = 100.0,
    sl: float = 95.0,
    tp: float | None = None,
    age_sec: int = 0,
    atr: float = 1.0,
    fees_per_unit: float = 0.1,
    funding_accum: float = 0.0,
):
    return PositionState(
        side=side,
        entry=entry,
        price=price,
        sl=sl,
        tp=tp,
        age_sec=age_sec,
        atr=atr,
        fees_per_unit=fees_per_unit,
        funding_accum=funding_accum,
    )


def test_reward_manager_max_r_exit():
    cfg = RewardCfg()
    rm = RewardManager(cfg)
    # LONG: denom = entry - sl = 10, need price >= entry + 3*denom = 130 for R_unreal >= max_R(=3)
    st = _st(side="LONG", entry=100.0, sl=90.0, price=130.0)
    dec = rm.update(st)
    assert dec.action == "MAX_R_EXIT"
    assert isinstance(dec.meta, dict) and dec.meta.get("R_unreal", 0) >= cfg.max_R


def test_reward_manager_time_exit():
    cfg = RewardCfg(max_position_age_sec=10)
    rm = RewardManager(cfg)
    st = _st(age_sec=11)
    dec = rm.update(st)
    assert dec.action == "TIME_EXIT"


def test_reward_manager_tp_hit_long():
    cfg = RewardCfg()
    rm = RewardManager(cfg)
    st = _st(side="LONG", entry=100.0, price=101.0, sl=95.0, tp=100.5)
    dec = rm.update(st)
    assert dec.action == "TP"


def test_reward_manager_breakeven_move_long():
    # breakeven_after_R default 0.8; use price so that R_unreal >= 0.8
    cfg = RewardCfg()
    rm = RewardManager(cfg)
    # denom = 100-90=10, need (price-100)/10 >= 0.8 → price >= 108
    st = _st(side="LONG", entry=100.0, sl=90.0, price=108.0, fees_per_unit=0.5)
    dec = rm.update(st)
    assert dec.action == "MOVE_TO_BREAKEVEN"
    assert dec.new_sl is not None
    assert dec.new_sl > st.sl  # moved up
    # expected be = 100 + 0.5
    # allow tiny float noise
    assert abs(dec.new_sl - 100.5) < 1e-7


def test_reward_manager_trailing_long():
    cfg = RewardCfg(trail_bps=20, trail_activate_at_R=0.5)
    rm = RewardManager(cfg)
    # denom = entry - sl. Use sl far enough to avoid MAX_R exit, but satisfy trail activation.
    # denom = 100 - 95 = 5; R_unreal = (106-100)/5 = 1.2 >= 0.5
    st = _st(side="LONG", entry=100.0, sl=95.0, price=106.0)
    dec = rm.update(st)
    assert dec.action in {"TRAIL_UP", "MOVE_TO_BREAKEVEN", "TP", "HOLD"}
    # If breakeven threshold also satisfied, MOVE_TO_BREAKEVEN can win; ensure at least not HOLD
    assert dec.action != "HOLD"
    if dec.action == "TRAIL_UP":
        assert dec.new_sl is not None
        # trail_bps=20 → 0.2% of price → 0.002*106 = 0.212; new_sl should be >= old sl
        assert dec.new_sl >= st.sl


def test_reward_manager_short_paths():
    cfg = RewardCfg()
    rm = RewardManager(cfg)
    # SHORT TP: price <= tp
    st_tp = _st(side="SHORT", entry=100.0, price=98.0, sl=105.0, tp=99.0)
    dec_tp = rm.update(st_tp)
    assert dec_tp.action == "TP"

    # SHORT trailing: denom = |entry - sl| = 5, need R_unreal >= 0.5 → (100-95)/5=1.0 >= 0.5
    st_tr = _st(side="SHORT", entry=100.0, sl=105.0, price=95.0)
    dec_tr = rm.update(st_tr)
    assert dec_tr.action in {"TRAIL_UP", "MOVE_TO_BREAKEVEN", "TP", "HOLD"}


def test_reward_manager_hold_when_no_rules_trigger():
    cfg = RewardCfg()
    rm = RewardManager(cfg)
    st = _st(side="LONG", entry=100.0, price=100.1, sl=90.0, tp=None, age_sec=1)
    dec = rm.update(st)
    assert dec.action == "HOLD"
