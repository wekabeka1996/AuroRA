from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional, Tuple, Mapping


@dataclass
class RiskConfig:
    dd_day_pct: float = 100.0  # percent of equity (loss cap), larger=looser
    max_concurrent: int = 10
    size_scale: float = 1.0


class RiskManager:
    """Simple risk caps manager: daily DD cap, max concurrent positions, size scaling.

    All inputs are taken from config with ENV overrides, and per-check state may override snapshot values.
    """

    def __init__(self, cfg: Optional[dict] = None) -> None:
        self.cfg = self.load(cfg or {}, dict(os.environ))

    @staticmethod
    def load(cfg: dict, env: Mapping[str, str]) -> RiskConfig:
        rcfg = (cfg.get('risk') or {})
        gates = (cfg.get('gates') or {})  # allow legacy location for dd cap
        # Prefer explicit risk.dd_day_pct, else env alias, else gates.daily_dd_limit_pct, else default
        dd_from_cfg = rcfg.get('dd_day_pct')
        if dd_from_cfg is None and 'daily_dd_limit_pct' in gates:
            dd_from_cfg = gates.get('daily_dd_limit_pct')
        dd_env = env.get('AURORA_DD_DAY_PCT')
        if dd_env is not None:
            dd_day_pct = float(dd_env)
        elif dd_from_cfg is not None:
            dd_day_pct = float(dd_from_cfg)
        else:
            dd_day_pct = 100.0
        max_concurrent = int(env.get('AURORA_MAX_CONCURRENT', rcfg.get('max_concurrent', 10)))
        size_scale = float(env.get('AURORA_SIZE_SCALE', rcfg.get('size_scale', 1.0)))
        # clip size_scale into [0,1]
        size_scale = max(0.0, min(1.0, size_scale))
        return RiskConfig(dd_day_pct=dd_day_pct, max_concurrent=max_concurrent, size_scale=size_scale)

    def snapshot(self) -> dict:
        return {
            'dd_day_pct': self.cfg.dd_day_pct,
            'max_concurrent': self.cfg.max_concurrent,
            'size_scale': self.cfg.size_scale,
        }

    def calc_notional(self, base_notional: float) -> float:
        return float(base_notional) * float(self.cfg.size_scale)

    @staticmethod
    def check_dd_day(pnl_today_pct: Optional[float], cap_pct: float) -> Tuple[bool, Optional[dict]]:
        if pnl_today_pct is None:
            return True, None
        used = -float(pnl_today_pct)  # losses are negative pnl, use positive used pct
        if used >= float(cap_pct):
            return False, {'dd_cap_pct': cap_pct, 'dd_used_pct': used, 'pnl_today_pct': pnl_today_pct}
        return True, None

    @staticmethod
    def check_concurrency(open_positions: Optional[int], max_concurrent: int) -> Tuple[bool, Optional[dict]]:
        if open_positions is None:
            return True, None
        if int(open_positions) >= int(max_concurrent):
            return False, {'open_positions': int(open_positions), 'max_concurrent': int(max_concurrent)}
        return True, None

    def decide(self, base_notional: float, *, pnl_today_pct: Optional[float], open_positions: Optional[int]) -> Tuple[bool, Optional[str], float, dict]:
        """Return (allow, reason, scaled_notional, ctx)."""
        # size_scale checks first (fail-closed if zero)
        scaled = self.calc_notional(base_notional)
        ctx = {
            'size_scale': self.cfg.size_scale,
            'base_notional': float(base_notional),
            'scaled_notional': float(scaled),
        }
        if self.cfg.size_scale <= 0.0:
            return False, 'risk_size_scale_zero', scaled, ctx

        ok, info = self.check_dd_day(pnl_today_pct, self.cfg.dd_day_pct)
        if not ok:
            ctx.update(info or {})
            return False, 'risk_dd_day_cap', scaled, ctx

        ok, info = self.check_concurrency(open_positions, self.cfg.max_concurrent)
        if not ok:
            ctx.update(info or {})
            return False, 'risk_max_concurrent', scaled, ctx

        # Minimal notional sanity (very small sizes). If caller didn't provide a positive
    # base_notional (e.g., test), historical 'shadow' mode references removed.
        try:
            bn = float(base_notional)
        except Exception:
            bn = 0.0
        if bn > 0.0 and scaled <= 0.0:
            return False, 'risk_notional_too_small', scaled, ctx

        return True, None, scaled, ctx
