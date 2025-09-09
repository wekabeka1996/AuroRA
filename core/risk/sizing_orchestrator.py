"""SizingOrchestrator — computes Kelly-based position size with clamps and caps.

Formulas (per spec):
  q_base = floor_lot( (r * E) / d )
    r: per-trade capital fraction (risk.per_trade_usd) OR absolute if >1? we treat as fraction if <=1 else absolute USD risk.
    E: account equity USD (risk_ctx.equity_usd)
    d: stop_dist_bps * price / 10_000  (per-unit $ risk)

  M = clamp(prod(multipliers), m_min, m_max)
  q_final = min(floor_lot(M * q_base), q_max_lev, q_max_exp) with minNotional check.

All monetary/price math uses Decimal for precision.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR
from typing import Dict, Any

from core.execution.router_v2 import OrderIntent, MarketSpec, KellyApplied
from core.aurora_event_logger import AuroraEventLogger


def _floor_lot(q: Decimal, lot: Decimal) -> Decimal:
    if lot <= 0:
        return q
    return (q / lot).to_integral_value(rounding=ROUND_FLOOR) * lot


@dataclass
class RiskCtx:
    equity_usd: Decimal
    cvar_limit_usd: Decimal
    leverage_max: Decimal
    exposure_cap_usd: Decimal


class SizingOrchestrator:
    def __init__(self, config: Dict[str, Any], event_logger: AuroraEventLogger | None = None):
        self.cfg = config or {}
        self.risk_cfg = self.cfg.get('risk', {})
        self.kelly_cfg = self.cfg.get('kelly', {})
        self.logger = event_logger or AuroraEventLogger()

        # defaults
        self.per_trade_frac = Decimal(str(self.risk_cfg.get('per_trade_usd', 0.0025)))  # fraction of equity
        self.cvar_limit_usd = Decimal(str(self.risk_cfg.get('cvar_limit_usd', 500)))
        self.leverage_max = Decimal(str(self.risk_cfg.get('leverage_max', 10)))
        self.exposure_cap_usd = Decimal(str(self.risk_cfg.get('exposure_cap_usd', 5000)))

        bounds = self.kelly_cfg.get('bounds', {})
        self.m_min = Decimal(str(bounds.get('m_min', 0.25)))
        self.m_max = Decimal(str(bounds.get('m_max', 1.25)))
        self.f_max = Decimal(str(bounds.get('f_max', 0.03)))  # portfolio max fraction risk (unused now)
        self.mult_defaults = self.kelly_cfg.get('multipliers', {}) or { 'cal':1.0,'reg':1.0,'liq':1.0,'dd':1.0,'lat':1.0 }

    def compute(self, intent: OrderIntent, market: MarketSpec) -> KellyApplied:
        # Extract risk ctx values (some may be strings)
        rc = intent.risk_ctx or {}
        equity_usd = Decimal(str(rc.get('equity_usd', '0')))
        if equity_usd <= 0:
            equity_usd = Decimal('0')

        # Price reference mid
        mid = market.mid if market.mid > 0 else (market.best_bid + market.best_ask)/Decimal('2')

        stop_dist_bps = Decimal(str(intent.stop_dist_bps))
        if stop_dist_bps <= 0:
            # fallback minimal distance to avoid division by zero
            stop_dist_bps = Decimal('1')

        # dollar risk per unit
        d = (stop_dist_bps * mid) / Decimal('10000')
        if d <= 0:
            d = mid / Decimal('10000')

        r = self.per_trade_frac
        if r > 1:
            # interpret as absolute USD risk if >1
            risk_capital = r
        else:
            risk_capital = r * equity_usd

        # Base quantity before Kelly multipliers
        if d > 0:
            q_base = risk_capital / d
        else:
            q_base = Decimal('0')

        # Multipliers product (placeholders =1.0 now)
        mults: Dict[str, Decimal] = {}
        prod = Decimal('1')
        for k, v in self.mult_defaults.items():
            dv = Decimal(str(v))
            mults[k] = dv
            prod *= dv

        M = prod
        if M < self.m_min:
            M = self.m_min
        if M > self.m_max:
            M = self.m_max

        q_adj = q_base * M

        # Leverage / exposure caps
        notional_mid = q_adj * mid
        q_max_lev = (equity_usd * self.leverage_max) / mid if mid > 0 else q_adj
        q_max_exp = self.exposure_cap_usd / mid if mid > 0 else q_adj

        q_cap = min(q_adj, q_max_lev, q_max_exp)

        # lot quantize
        q_final = _floor_lot(q_cap, market.lot_size)
        if q_final <= 0:
            q_final = Decimal('0')

        # min notional guard
        if q_final * mid < market.min_notional:
            # attempt bump to min notional boundary
            needed = (market.min_notional / mid) if mid > 0 else market.min_notional
            q_final = _floor_lot(needed, market.lot_size)
            if q_final * mid < market.min_notional:
                # still below — set zero
                q_final = Decimal('0')

        # --- CVaR scaling stub ---
        # risk_ctx may provide current_cvar_usd and est_increment_per_unit_usd
        try:
            cvar_curr = Decimal(str(rc.get('cvar_curr_usd', '0')))
        except Exception:
            cvar_curr = Decimal('0')
        try:
            cvar_limit = Decimal(str(rc.get('cvar_limit_usd', self.cvar_limit_usd)))
        except Exception:
            cvar_limit = self.cvar_limit_usd
        try:
            d_cvar_per_unit = Decimal(str(rc.get('delta_cvar_per_unit_usd', '0')))
        except Exception:
            d_cvar_per_unit = Decimal('0')
        if d_cvar_per_unit < 0:
            d_cvar_per_unit = abs(d_cvar_per_unit)
        # projected cvar after placing q_final
        projected = cvar_curr + d_cvar_per_unit * q_final
        gamma = Decimal('1')
        if cvar_limit > 0 and d_cvar_per_unit > 0:
            if projected > cvar_limit:
                # Target remaining headroom (may be negative)
                headroom = cvar_limit - cvar_curr
                if headroom <= 0:
                    # No capacity; force zero
                    if q_final > 0:
                        self.logger.emit('CVAR.SHIFT', {
                            'gamma': 0.0,
                            'q_before': str(q_final),
                            'q_after': '0',
                            'cvar_curr_usd': float(cvar_curr),
                            'cvar_limit_usd': float(cvar_limit),
                            'delta_cvar_per_unit_usd': float(d_cvar_per_unit)
                        })
                    q_final = Decimal('0')
                else:
                    # Solve gamma so cvar_curr + d_cvar_per_unit*(gamma*q_final) <= cvar_limit
                    try:
                        gamma = headroom / (d_cvar_per_unit * q_final) if q_final > 0 else Decimal('0')
                    except Exception:
                        gamma = Decimal('0')
                    if gamma < 0:
                        gamma = Decimal('0')
                    if gamma > 1:
                        gamma = Decimal('1')
                    scaled = _floor_lot(q_final * gamma, market.lot_size)
                    # Recompute projected after scaling
                    if scaled < q_final:
                        self.logger.emit('CVAR.SHIFT', {
                            'gamma': float(gamma),
                            'q_before': str(q_final),
                            'q_after': str(scaled),
                            'cvar_curr_usd': float(cvar_curr),
                            'cvar_limit_usd': float(cvar_limit),
                            'delta_cvar_per_unit_usd': float(d_cvar_per_unit)
                        })
                    q_final = scaled

        kelly = KellyApplied(
            f_raw=float(r),
            f_portfolio=float(r),
            multipliers={k: float(v) for k,v in mults.items()},
            f_final=float(r * M if r <= 1 else M),
            qty_final=q_final
        )
        return kelly

__all__ = ['SizingOrchestrator','RiskCtx']
