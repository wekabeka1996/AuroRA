from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional, List
from .config_loader import RewardCfg


@dataclass
class PositionState:
    # Accept plain str to satisfy static analysis in tests while semantically expecting 'LONG' or 'SHORT'
    side: Literal['LONG', 'SHORT'] | str
    entry: float
    price: float
    sl: float
    tp: Optional[float]
    age_sec: int
    atr: float
    fees_per_unit: float
    funding_accum: float
    # New fields for v1.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    gross_qty: float = 0.0
    net_qty: float = 0.0
    trail_px: Optional[float] = None
    be_px: Optional[float] = None
    last_scale_in_ts: int = 0
    tp_hits: Optional[List[float]] = None  # TP levels hit so far
    tp_levels_bps: Optional[List[float]] = None
    tp_sizes: Optional[List[float]] = None
    
    def __post_init__(self):
        if self.tp_hits is None:
            self.tp_hits = []
        if self.tp_levels_bps is None:
            self.tp_levels_bps = []
        if self.tp_sizes is None:
            self.tp_sizes = []


@dataclass
class RewardDecision:
    action: Literal['HOLD','TP','TRAIL_UP','MOVE_TO_BREAKEVEN','TIME_EXIT','MAX_R_EXIT','SCALE_IN','REDUCE','CLOSE']
    new_sl: Optional[float] = None
    new_tp: Optional[float] = None
    scale_qty: Optional[float] = None
    reduce_qty: Optional[float] = None
    tp_level_hit: Optional[float] = None
    meta: dict | None = None


class RewardManager:
    def __init__(self, cfg: RewardCfg):
        self.cfg = cfg
        self._last_scale_in_ts = 0

    def update(self, st: PositionState) -> RewardDecision:
        """Enhanced reward management with TP ladder, breakeven, trail-stop, and scale-in"""
        side_sign = 1.0 if st.side == 'LONG' else -1.0
        
        # Calculate current R/R
        if st.sl is not None and st.sl != st.entry:
            current_rr = abs((st.price - st.entry) / (st.entry - st.sl))
        else:
            current_rr = 0.0
            
        # Max-R exit
        if current_rr >= float(self.cfg.max_R):
            return RewardDecision(action='MAX_R_EXIT', meta={'R_unreal': current_rr})

        # Time exit (TTL)
        ttl_sec = self.cfg.ttl_minutes * 60
        if st.age_sec > ttl_sec:
            return RewardDecision(action='TIME_EXIT', meta={'age_sec': st.age_sec, 'ttl_sec': ttl_sec})

        # No-progress exit
        if abs(st.unrealized_pnl) < self.cfg.no_progress_eps_bps * st.entry / 1e4:
            if st.age_sec > self.cfg.stuck_dt_s:
                return RewardDecision(action='TIME_EXIT', meta={'reason': 'no_progress', 'age_sec': st.age_sec})

        # TP ladder management
        tp_decision = self._check_tp_ladder(st, side_sign)
        if tp_decision:
            return tp_decision

        # Breakeven management
        be_decision = self._check_breakeven(st, current_rr, side_sign)
        if be_decision:
            return be_decision

        # Trail-stop management
        trail_decision = self._check_trail_stop(st, side_sign)
        if trail_decision:
            return trail_decision

        # Anti-martingale scale-in
        if self.cfg.scale_in_enabled:
            scale_decision = self._check_scale_in(st, current_rr)
            if scale_decision:
                return scale_decision

        return RewardDecision(action='HOLD')

    def _check_tp_ladder(self, st: PositionState, side_sign: float) -> Optional[RewardDecision]:
        """Check TP ladder levels and return exit decision if hit"""
        if not st.tp_levels_bps or not st.tp_sizes or st.tp_hits is None:
            return None
            
        # Calculate current profit in bps
        profit_bps = side_sign * (st.price - st.entry) * 1e4 / st.entry
        
        # Find next TP level not yet hit
        for i, (tp_bps, tp_size) in enumerate(zip(st.tp_levels_bps, st.tp_sizes)):
            if tp_bps not in st.tp_hits and profit_bps >= tp_bps:
                # Mark this level as hit
                st.tp_hits.append(tp_bps)
                # Calculate reduce quantity
                reduce_qty = st.net_qty * tp_size
                return RewardDecision(
                    action='REDUCE',
                    reduce_qty=reduce_qty,
                    tp_level_hit=tp_bps,
                    meta={'tp_level': i, 'profit_bps': profit_bps, 'reduce_pct': tp_size}
                )
        
        return None

    def _check_breakeven(self, st: PositionState, current_rr: float, side_sign: float) -> Optional[RewardDecision]:
        """Check if breakeven should be activated"""
        if current_rr >= self.cfg.breakeven_after_R:
            # Calculate breakeven price including fees and buffer
            be_price = st.entry + side_sign * (st.fees_per_unit + self.cfg.be_buffer_bps * st.entry / 1e4)
            
            # Check if we should move SL to breakeven
            if st.side == 'LONG' and (st.sl is None or be_price > st.sl):
                return RewardDecision(action='MOVE_TO_BREAKEVEN', new_sl=be_price)
            elif st.side == 'SHORT' and (st.sl is None or be_price < st.sl):
                return RewardDecision(action='MOVE_TO_BREAKEVEN', new_sl=be_price)
        
        return None

    def _check_trail_stop(self, st: PositionState, side_sign: float) -> Optional[RewardDecision]:
        """Check trail-stop logic using ATR-based distance"""
        if st.atr <= 0:
            return None
            
        # Calculate trail distance
        trail_dist = self.cfg.trail_atr_k * st.atr
        
        if st.side == 'LONG':
            # Update trail high water mark
            new_trail = max(st.trail_px or st.entry, st.price - trail_dist)
            if st.trail_px is None or new_trail > st.trail_px:
                st.trail_px = new_trail
                return RewardDecision(action='TRAIL_UP', new_sl=new_trail)
        else:  # SHORT
            # Update trail low water mark
            new_trail = min(st.trail_px or st.entry, st.price + trail_dist)
            if st.trail_px is None or new_trail < st.trail_px:
                st.trail_px = new_trail
                return RewardDecision(action='TRAIL_UP', new_sl=new_trail)
        
        return None

    def _check_scale_in(self, st: PositionState, current_rr: float) -> Optional[RewardDecision]:
        """Check anti-martingale scale-in conditions"""
        now_ts = st.age_sec  # Using age_sec as timestamp proxy
        
        # Check cooldown
        if now_ts - st.last_scale_in_ts < self.cfg.scale_in_cooldown_s:
            return None
            
        # Only scale in on increasing edge (anti-martingale)
        # This would need edge estimate from caller - for now, use simplified logic
        if current_rr > 0.5:  # Simplified: scale in if profitable
            # Calculate scale-in amount with hysteresis
            scale_qty = min(
                self.cfg.scale_in_rho * st.net_qty,
                self.cfg.scale_in_max_add_per_step * st.net_qty
            )
            
            if scale_qty > 0:
                st.last_scale_in_ts = now_ts
                return RewardDecision(
                    action='SCALE_IN',
                    scale_qty=scale_qty,
                    meta={'current_rr': current_rr, 'scale_pct': scale_qty / st.net_qty}
                )
        
        return None
