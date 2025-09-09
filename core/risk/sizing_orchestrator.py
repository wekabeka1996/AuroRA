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
from typing import Dict, Any, List

from core.execution.router_v2 import OrderIntent, MarketSpec, KellyApplied
from core.aurora_event_logger import AuroraEventLogger
from .multipliers import LambdaOrchestrator
from .evtcvar import EVTCVaR
from .cvar_gate import delta_cvar_position, allow_trade
from .portfolio_kelly import compute_portfolio_fraction
from tools.metrics_exporter import METRICS


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
        self.lambda_orchestrator = LambdaOrchestrator(self.cfg)
        cvar_cfg = (self.risk_cfg or {}).get('cvar', {})
        self.cvar_alpha = float(cvar_cfg.get('alpha', 0.95))
        self.min_exceedances = int(cvar_cfg.get('min_exceedances', 500))

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

        # Compute micro context for multipliers
        micro_ctx = {
            'half_spread_bps': (Decimal(str(market.spread_bps)) / Decimal('2')),
            'latency_p95_ms': Decimal(str((self.cfg.get('execution', {}).get('sla', {}) or {}).get('p95_ms', 0))),
            'ece': Decimal(str(rc.get('ece', 0))),
            'regime': rc.get('regime', 'trend'),
        }
        lambdas = self.lambda_orchestrator.compute(intent.__dict__, rc, micro_ctx)
        # Build multipliers map and product
        mults: Dict[str, Decimal] = {k: Decimal(str(v)) for k, v in lambdas.items()}
        prod = Decimal('1')
        for dv in mults.values():
            prod *= dv
        M = prod
        if M < self.m_min:
            M = self.m_min
        if M > self.m_max:
            M = self.m_max
        self.logger.emit('LAMBDA.UPDATE', {'cal': float(mults.get('cal', Decimal('1'))), 'reg': float(mults.get('reg', Decimal('1'))), 'liq': float(mults.get('liq', Decimal('1'))), 'dd': float(mults.get('dd', Decimal('1'))), 'lat': float(mults.get('lat', Decimal('1'))), 'M': float(M)})
        try:
            METRICS.aurora.set_lambda_m(float(M))
        except Exception:
            pass

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

        # min notional guard with bump (ceil to required qty then quantize)
        if q_final * mid < market.min_notional and mid > 0:
            needed = (market.min_notional / mid)
            # ceil to lot: add small epsilon to ensure bump up
            steps = (needed / market.lot_size).to_integral_value(rounding=ROUND_FLOOR)
            if steps * market.lot_size < needed:
                steps = steps + 1
            q_bumped = steps * market.lot_size
            if q_bumped * mid >= market.min_notional:
                q_final = q_bumped
            else:
                q_final = Decimal('0')

        # --- Portfolio-Kelly adjustment (LW shrink) before CVaR ---
        f_port = None
        try:
            # Read portfolio context (support both flat and nested keys)
            port = rc.get('portfolio', {}) if isinstance(rc.get('portfolio', {}), dict) else {}
            symbols = rc.get('portfolio_symbols') or port.get('symbols')
            cov = rc.get('portfolio_cov') or port.get('cov')
            pv_usd = rc.get('portfolio_pv_usd') or port.get('pv_usd')
            if symbols is not None and cov is not None and pv_usd is not None and len(symbols) == len(pv_usd):
                # Candidate PV for this trade
                dir_sign = Decimal('1') if intent.side.upper() == 'BUY' else Decimal('-1')
                pv_new = (q_final * mid * dir_sign)
                # Build weights including candidate
                import numpy as _np  # local import to avoid hard dep at load time
                pv_vec = _np.asarray([float(x) for x in pv_usd], dtype=float)
                # If symbol exists, add PV to it; else skip adjustment to avoid cov expansion
                if intent.symbol in symbols and float(equity_usd) > 0:
                    idx = symbols.index(intent.symbol)
                    pv_vec = pv_vec.copy()
                    pv_vec[idx] += float(pv_new)
                    w_vec = pv_vec / float(equity_usd)
                    f_raw_frac = float(r) if r <= 1 else 1.0
                    f_port_val = compute_portfolio_fraction(
                        f_raw=f_raw_frac,
                        symbols=symbols,
                        w_vec=w_vec,
                        cov=_np.asarray(cov, dtype=float),
                        f_max=float(self.f_max),
                        min_var_eps=float((self.cfg.get('portfolio', {}) or {}).get('cov', {}).get('min_var_eps', 1e-8)),
                    )
                    f_port = float(f_port_val)
                    # Scale qty by f_port/f_raw and re-apply quantization and caps/bump
                    scale = Decimal(str(f_port)) / (r if r <= 1 else Decimal('1')) if (r if r <= 1 else Decimal('1')) > 0 else Decimal('1')
                    q_scaled = q_final * scale
                    # re-apply caps
                    q_cap2 = min(q_scaled, q_max_lev, q_max_exp)
                    q_final = _floor_lot(q_cap2, market.lot_size)
                    if q_final * mid < market.min_notional and mid > 0:
                        needed = (market.min_notional / mid)
                        steps = (needed / market.lot_size).to_integral_value(rounding=ROUND_FLOOR)
                        if steps * market.lot_size < needed:
                            steps = steps + 1
                        q_bumped2 = steps * market.lot_size
                        q_final = q_bumped2 if q_bumped2 * mid >= market.min_notional else Decimal('0')
        except Exception:
            # Portfolio adjustment is optional; ignore errors
            pass

        # --- CVaR gate using EVT or fallback ---
        try:
            cvar_curr = float(Decimal(str(rc.get('cvar_curr_usd', '0'))))
        except Exception:
            cvar_curr = 0.0
        try:
            cvar_limit = float(Decimal(str(rc.get('cvar_limit_usd', self.cvar_limit_usd))))
        except Exception:
            cvar_limit = float(self.cvar_limit_usd)

        # EVT fit if losses provided; else fallback
        losses: List[float] = []
        raw_losses = rc.get('losses', None)
        if isinstance(raw_losses, list):
            try:
                losses = [float(x) for x in raw_losses]
            except Exception:
                losses = []

        delta = 0.0
        if losses:
            evt = EVTCVaR(min_exceedances=self.min_exceedances)
            fit = evt.fit(losses, u_quantile=self.cvar_alpha)
            self.logger.emit('CVAR.EVT.FIT', fit)
            # Use fallback delta as conservative contribution from current position size
            delta = delta_cvar_position(int(stop_dist_bps), mid, q_final)
        else:
            delta = delta_cvar_position(int(stop_dist_bps), mid, q_final)

        allow = allow_trade(cvar_curr, delta, cvar_limit)
        self.logger.emit('CVAR.GATE', {'cvar_curr': cvar_curr, 'delta': float(delta), 'limit': cvar_limit, 'allow': bool(allow)})
        if not allow:
            if q_final > 0:
                self.logger.emit('CVAR.SHIFT', {'gamma': 0.0, 'q_before': str(q_final), 'q_after': '0', 'cvar_curr_usd': cvar_curr, 'cvar_limit_usd': cvar_limit, 'delta_cvar_usd': float(delta)})
            q_final = Decimal('0')

        kelly = KellyApplied(
            f_raw=float(r),
            f_portfolio=float(f_port if f_port is not None else r),
            multipliers={k: float(v) for k,v in mults.items()},
            f_final=float(min(self.f_max, (r if r <= 1 else Decimal('1')) * M)),
            qty_final=q_final
        )
        self.logger.emit('KELLY.APPLIED', {'f_raw': float(r), 'f_port': float(f_port if f_port is not None else (float(r))), 'M': float(M), 'f_final': kelly.f_final, 'qty_final': str(q_final)})
        try:
            METRICS.aurora.set_f_port(float(f_port if f_port is not None else (float(r))))
        except Exception:
            pass
        return kelly

__all__ = ['SizingOrchestrator','RiskCtx']
