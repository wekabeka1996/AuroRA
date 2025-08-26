from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional
from .config_loader import RewardCfg


@dataclass
class PositionState:
    side: Literal['LONG', 'SHORT']
    entry: float
    price: float
    sl: float
    tp: Optional[float]
    age_sec: int
    atr: float
    fees_per_unit: float
    funding_accum: float


@dataclass
class RewardDecision:
    action: Literal['HOLD','TP','TRAIL_UP','MOVE_TO_BREAKEVEN','TIME_EXIT','MAX_R_EXIT']
    new_sl: Optional[float] = None
    meta: dict | None = None


class RewardManager:
    def __init__(self, cfg: RewardCfg):
        self.cfg = cfg

    def update(self, st: PositionState) -> RewardDecision:
        # Simple placeholder logic consistent with spec structure
        side_sign = 1.0 if st.side == 'LONG' else -1.0
        R_unreal = (st.price - st.entry) * side_sign / max(1e-12, abs(st.entry - st.sl))

        # Max-R exit
        if R_unreal >= float(self.cfg.max_R):
            return RewardDecision(action='MAX_R_EXIT', meta={'R_unreal': R_unreal})

        # Time exit
        if st.age_sec > int(self.cfg.max_position_age_sec):
            return RewardDecision(action='TIME_EXIT', meta={'age_sec': st.age_sec})

        # TP hit
        if st.tp is not None:
            if (st.price >= st.tp and st.side == 'LONG') or (st.price <= st.tp and st.side == 'SHORT'):
                return RewardDecision(action='TP')

        # Breakeven
        if R_unreal >= float(self.cfg.breakeven_after_R):
            be = st.entry + side_sign * (st.fees_per_unit + 1e-8)
            if (st.side == 'LONG' and be > st.sl) or (st.side == 'SHORT' and be < st.sl):
                return RewardDecision(action='MOVE_TO_BREAKEVEN', new_sl=be)

        # Trailing
        if R_unreal >= float(self.cfg.trail_activate_at_R):
            M = st.price
            trail_dist = float(self.cfg.trail_bps) * M / 1e4
            if st.side == 'LONG':
                new_sl = max(st.sl, st.price - trail_dist)
                if new_sl > st.sl:
                    return RewardDecision(action='TRAIL_UP', new_sl=new_sl)
            else:
                new_sl = min(st.sl, st.price + trail_dist)
                if new_sl < st.sl:
                    return RewardDecision(action='TRAIL_UP', new_sl=new_sl)

        return RewardDecision(action='HOLD')
