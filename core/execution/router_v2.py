"""RouterV2 — canonical routing & validation pipeline (skeleton)

NOTE: Implementation intentionally omitted per task constraints (design & scaffolding only).
Fill in logic following documented pipeline in execution plan.
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, ROUND_FLOOR, ROUND_CEILING
from typing import Optional, List, Dict, Any, Literal, Union
import hashlib

from core.aurora_event_logger import AuroraEventLogger
from core.tca.fill_prob import p_fill_at_T
from tools.metrics_exporter import METRICS

# --- Data Contracts (mirror of agreed v1.0) ---
@dataclass
class OrderIntent:
    intent_id: str
    timestamp_ms: int
    symbol: str
    side: Literal['BUY','SELL']
    dir: int  # +1 / -1
    strategy_id: str
    expected_return_bps: int
    stop_dist_bps: int
    tp_targets_bps: List[int]
    risk_ctx: Dict[str, Any]
    regime_ctx: Dict[str, Any]
    exec_prefs: Dict[str, Any]
    qty_hint: Optional[Decimal] = None  # temporary until sizing orchestrator integrated

@dataclass
class EdgeBudget:
    dir: int
    raw: int
    fees: int
    slip_est: int
    adv_sel: int
    lat_cost: int
    rebates: int
    pi_fill_Tsla: float
    T_SLA_ms: int
    net_after_tca: int
    reason: str

@dataclass
class KellyApplied:
    f_raw: float
    f_portfolio: float
    multipliers: Dict[str, float]
    f_final: float
    qty_final: Decimal

@dataclass
class RoutedOrderPlan:
    mode: Literal['maker','taker']
    order_type: Literal['LIMIT','MARKET','STOP_MARKET','TAKE_PROFIT_MARKET']
    qty: str
    client_order_id: str
    group_id: str
    tca: EdgeBudget
    sizing: KellyApplied | None
    governance_state: str
    xai_trace_id: str
    price: Optional[str] = None
    bracket_children: Optional[List[Dict[str, Any]]] = None

@dataclass
class DenyDecision:
    code: str
    stage: str
    reason: str
    diagnostics: Dict[str, Any]
    validations: List[Dict[str, Any]]

@dataclass
class MarketSpec:
    tick_size: Decimal
    lot_size: Decimal
    min_notional: Decimal
    maker_fee_bps: int
    taker_fee_bps: int
    best_bid: Decimal
    best_ask: Decimal
    spread_bps: float
    mid: Decimal

class RouterV2:
    """RouterV2 — повна імплементація маршрутизації maker/taker з економічним та SLA контекстом.

    Лише Decimal усередині; зовнішні числові значення у bps інтегеризуються.
    """
    def __init__(self, *, config: Dict[str, Any], event_logger: AuroraEventLogger | None = None):
        self.cfg = config or {}
        r = self.cfg.get('execution', {}).get('router', {})
        sla = self.cfg.get('execution', {}).get('sla', {})
        self.p_min_fill = Decimal(str(r.get('p_min_fill', 0.25)))
        self.maker_spread_ok_bps = Decimal(str(r.get('maker_spread_ok_bps', 2.0)))
        self.spread_deny_bps = Decimal(str(r.get('spread_deny_bps', 8.0)))
        self.switch_margin_bps = Decimal(str(r.get('switch_margin_bps', 0.2)))
        self.maker_offset_bps = Decimal(str(r.get('maker_offset_bps', 0.1)))
        self.percent_price_limit_bps = Decimal(str(r.get('percent_price_limit_bps', 75.0)))
        # new economics config
        self.capture_eta = Decimal(str(r.get('capture_eta', 0.35)))  # fraction of half-spread captured when maker fills
        self.rebate_mode = bool(r.get('rebate_mode', True))  # include maker rebate delta if True
        self.pfill_min = Decimal(str(r.get('pfill_min', 0.55)))  # viability threshold => LOW_PFILL.DENY
        self.kappa_bps_per_ms = Decimal(str(sla.get('kappa_bps_per_ms', 0.01)))  # already in bps/ms
        self.max_latency_ms = Decimal(str(sla.get('max_latency_ms', 250.0)))
        self.edge_floor_bps = Decimal(str(sla.get('edge_floor_bps', 0.0)))
        # legacy threshold kept for backward compat but superseded by pfill_min
        self.pi_fill_min = self.pfill_min
        self.event_logger = event_logger or AuroraEventLogger()
        # p_fill parameters from config (optional)
        try:
            pfill_cfg = (self.cfg.get('pfill') or {}) | ((self.cfg.get('execution', {}) or {}).get('pfill') or {})
        except Exception:
            pfill_cfg = (self.cfg.get('pfill') or {})
        beta_cfg = (pfill_cfg.get('beta') or {}) if isinstance(pfill_cfg, dict) else {}
        # Normalize keys to expected names b0..b4 if provided differently
        if isinstance(beta_cfg, dict) and beta_cfg:
            # allow aliases like beta0..beta4
            beta_norm = {}
            for k, v in beta_cfg.items():
                k2 = str(k).lower().strip()
                if k2 in {'b0','b1','b2','b3','b4'}:
                    beta_norm[k2] = float(v)
                elif k2 in {'beta0','beta_0'}:
                    beta_norm['b0'] = float(v)
                elif k2 in {'beta1','beta_1'}:
                    beta_norm['b1'] = float(v)
                elif k2 in {'beta2','beta_2'}:
                    beta_norm['b2'] = float(v)
                elif k2 in {'beta3','beta_3'}:
                    beta_norm['b3'] = float(v)
                elif k2 in {'beta4','beta_4'}:
                    beta_norm['b4'] = float(v)
            self._pfill_beta: Dict[str, float] | None = beta_norm or None
        else:
            self._pfill_beta = None
        try:
            eps_val = pfill_cfg.get('eps') if isinstance(pfill_cfg, dict) else None
            self._pfill_eps: float | None = (float(eps_val) if eps_val is not None else None)
        except Exception:
            self._pfill_eps = None

    # ---- helpers ----
    @staticmethod
    def _floor_qty(q: Decimal, lot: Decimal) -> Decimal:
        if lot <= 0:
            return q
        return (q / lot).to_integral_value(rounding=ROUND_FLOOR) * lot

    @staticmethod
    def _floor_price_buy(p: Decimal, tick: Decimal) -> Decimal:
        if tick <= 0:
            return p
        return (p / tick).to_integral_value(rounding=ROUND_FLOOR) * tick

    @staticmethod
    def _ceil_price_sell(p: Decimal, tick: Decimal) -> Decimal:
        if tick <= 0:
            return p
        # ceil via negative floor
        return (-( -p / tick).to_integral_value(rounding=ROUND_FLOOR)) * tick

    @staticmethod
    def _int_bps(x: Decimal) -> int:
        # Floor toward zero for deterministic logging
        if x >= 0:
            return int(x.to_integral_value(rounding=ROUND_FLOOR))
        return -int((-x).to_integral_value(rounding=ROUND_FLOOR))

    def _p_fill(self, features: Dict[str, Any], spread_bps: Decimal) -> Decimal:
        """Compute maker fill probability using hazard-style v1 model.

        Expected feature keys (with fallbacks):
        - 'obi' in [-1,1]
        - 'queue_pos' >=0
        - 'T_ms' or fallback to 'pred_latency_ms' or provided caller latency
        """
        try:
            side = features.get('side_override')  # optional for testing; else infer later
            # We don't have direct side here; will be set at call site via features if needed.
            # For backward compat, treat unknown side as BUY symmetry.
            if side not in ('BUY', 'SELL'):
                side = 'BUY'
            queue_pos = float(features.get('queue_pos', 0.0))
            depth_at_price = float(features.get('depth_at_price', features.get('depth', 1.0)))
            obi = float(features.get('obi', 0.0))
            T_ms = float(features.get('T_ms', features.get('pred_latency_ms', 0.0)))
            p = p_fill_at_T(
                side=side,
                queue_pos=queue_pos,
                depth_at_price=depth_at_price,
                obi=obi,
                spread_bps=float(spread_bps),
                T_ms=T_ms,
                beta=self._pfill_beta,
                eps=(self._pfill_eps if self._pfill_eps is not None else 1e-4),
            )
            # Clip and convert to Decimal deterministically
            if p < 0.0:
                p = 0.0
            elif p > 1.0:
                p = 1.0
            return Decimal(str(p))
        except Exception:
            # robust fallback to conservative small probability
            return Decimal('0.0')

    # ---- main API ----
    def route(self, intent: OrderIntent, market: MarketSpec, latency_ms: float, features: Dict[str, Any]) -> Union[RoutedOrderPlan, DenyDecision]:
        validations: List[Dict[str, Any]] = []
        stage = 'normalize'
        try:
            # 1 Normalize & guards
            side = intent.side.upper()
            if side not in ('BUY','SELL'):
                return DenyDecision(code='INTENT_INVALID', stage='normalize', reason='unknown side', diagnostics={'side': side}, validations=[])
            dir_sign = Decimal('1') if side == 'BUY' else Decimal('-1')

            # 2 MarketSpec already provided (assumed validated upstream)
            tick = market.tick_size
            lot = market.lot_size
            min_notional = market.min_notional

            # 3 Quantize qty (price later). Use qty_hint or deny if missing
            if intent.qty_hint is None:
                return DenyDecision(code='INTENT_INVALID', stage='quantize', reason='qty_hint missing', diagnostics={}, validations=[])
            qty_raw = Decimal(str(intent.qty_hint))
            if qty_raw <= 0:
                return DenyDecision(code='INTENT_INVALID', stage='quantize', reason='qty<=0', diagnostics={'qty_raw': str(qty_raw)}, validations=[])
            qty = self._floor_qty(qty_raw, lot)
            if qty <= 0:
                return DenyDecision(code='LOT_SIZE', stage='quantize', reason='quantized qty zero', diagnostics={'qty_raw': str(qty_raw),'lot': str(lot)}, validations=[])

            best_bid = market.best_bid
            best_ask = market.best_ask
            mid = market.mid
            ref_px = mid if mid > 0 else (best_bid + best_ask) / Decimal('2')

            notional = qty * ref_px
            if notional < min_notional:
                return DenyDecision(code='MIN_NOTIONAL', stage='quantize', reason='notional < min', diagnostics={'notional': str(notional), 'min': str(min_notional)}, validations=[])

            # 4 Spread / marks
            spread_bps = Decimal(str(market.spread_bps))
            half_spread_bps = spread_bps / Decimal('2')
            if spread_bps >= self.spread_deny_bps:
                return DenyDecision(code='SPREAD_DENY', stage='spread', reason='spread too wide', diagnostics={'spread_bps': self._int_bps(spread_bps), 'limit': self._int_bps(self.spread_deny_bps)}, validations=[])

            # 5 Latency (pred latency optionally passed in features)
            pred_latency_ms = Decimal(str(features.get('pred_latency_ms', latency_ms)))
            if pred_latency_ms > self.max_latency_ms:
                return DenyDecision(code='SLA_LATENCY', stage='sla_predict', reason='pred latency > max', diagnostics={'pred_latency_ms': float(pred_latency_ms)}, validations=[])
            # lat_cost using configured kappa (already bps per ms)
            lat_cost_bps = - self.kappa_bps_per_ms * pred_latency_ms

            # 6 Fees/Rebates (configurable rebate inclusion)
            maker_fee_bps = Decimal(str(market.maker_fee_bps))  # positive cost
            taker_fee_bps = Decimal(str(market.taker_fee_bps))  # positive cost
            if self.rebate_mode:
                fee_delta = Decimal(str(market.taker_fee_bps - market.maker_fee_bps))
                maker_rebate_bps = fee_delta if fee_delta > 0 else Decimal('0')
            else:
                maker_rebate_bps = Decimal('0')
            rebates_bps = maker_rebate_bps

            # 7 Slippage/ADV placeholders
            slip_t = Decimal(str(features.get('slip_t_bps', 0)))  # negative or 0 expected
            adv_sel = Decimal(str(features.get('adv_sel_bps', 0)))  # negative or 0
            if slip_t > 0:
                slip_t = -abs(slip_t)
            if adv_sel > 0:
                adv_sel = -abs(adv_sel)

            # 8 p_fill
            p_fill = self._p_fill(features, spread_bps)
            # ensure Decimal
            p_fill = Decimal(str(p_fill))

            # 9 Expected edges
            raw_edge = Decimal(str(intent.expected_return_bps)) * dir_sign  # directional
            edge_lat = raw_edge + lat_cost_bps
            # Fees components for formulas (fees negative in EdgeBudget, rebates positive)
            fees_m_comp = -maker_fee_bps
            fees_t_comp = -taker_fee_bps
            # Maker expected: partial capture of half-spread: capture_eta * half_spread
            spread_contrib = self.capture_eta * half_spread_bps
            E_m = p_fill * (edge_lat + spread_contrib + rebates_bps + fees_m_comp + adv_sel)
            # Taker expected: subtract half-spread, add fees_t + adv_sel + slippage
            E_t = edge_lat - half_spread_bps + fees_t_comp + adv_sel + slip_t

            # 10 SLA guard vs edge floor after latency
            if edge_lat <= self.edge_floor_bps:
                return DenyDecision(code='EDGE_FLOOR', stage='sla_edge', reason='edge after latency below floor', diagnostics={'edge_lat': self._int_bps(edge_lat), 'floor': self._int_bps(self.edge_floor_bps)}, validations=[])

            # 11 Route decision
            route: Optional[str] = None
            why_code: str = ''
            # TIF incompatibility: post_only cannot be used with IOC/FOK
            tif = str(intent.exec_prefs.get('tif', 'GTC')).upper()
            if intent.exec_prefs.get('post_only', False) and tif in ('IOC','FOK'):
                return DenyDecision(code='POST_ONLY_UNAVAILABLE', stage='decide', reason='post_only incompatible with IOC/FOK', diagnostics={'tif': tif}, validations=[])
            maker_viable = (p_fill >= self.pi_fill_min) and (spread_bps <= self.maker_spread_ok_bps)
            e_m_int = self._int_bps(E_m)
            e_t_int = self._int_bps(E_t)
            if E_m <= 0 and E_t <= 0:
                return DenyDecision(code='EDGE_DENY', stage='decide', reason='both expected <=0', diagnostics={'E_m': e_m_int, 'E_t': e_t_int, 'p_fill': float(p_fill)}, validations=[])
            # if post_only requested but maker not viable => explicit denial
            if intent.exec_prefs.get('post_only', False) and not maker_viable:
                # If post_only but maker not viable: deny when taker isn't clearly better; otherwise allow taker fallback
                if E_t <= 0:
                    return DenyDecision(code='LOW_PFILL.DENY', stage='decide', reason='post_only requested but maker not viable (low p_fill or spread)', diagnostics={'p_fill': float(p_fill), 'pfill_min': float(self.pi_fill_min), 'spread_bps': self._int_bps(spread_bps)}, validations=[])
                # If taker positive, proceed to taker route selection below
            if maker_viable and E_m > 0 and (E_m - E_t) >= self.switch_margin_bps:
                route = 'maker'
                why_code = 'MAKER_SELECTED'
            else:
                # fallback to taker if taker positive
                if E_t > 0:
                    route = 'taker'
                    why_code = 'TAKER_SELECTED'
                else:
                    # maker may still be positive but not viable due to p_fill
                    if E_m > 0:
                        return DenyDecision(code='LOW_PFILL.DENY', stage='decide', reason='p_fill below min viability threshold', diagnostics={'p_fill': float(p_fill), 'pfill_min': float(self.pi_fill_min)}, validations=[])
                    return DenyDecision(code='EDGE_DENY', stage='decide', reason='no viable route', diagnostics={'E_m': e_m_int, 'E_t': e_t_int}, validations=[])

            # 12 Build plan (price for maker)
            price: Optional[Decimal] = None
            if route == 'maker':
                # offset price
                offset_px = (mid * self.maker_offset_bps) / Decimal('10000')
                if side == 'BUY':
                    candidate = best_bid - offset_px
                    px = self._floor_price_buy(candidate, tick)
                    # enforce post-only (не перетнути bid)
                    if px > best_bid:
                        px = self._floor_price_buy(best_bid - tick, tick)
                    price = px
                    if price > best_bid:
                        return DenyDecision(code='POST_ONLY_BREACH', stage='post_only', reason='buy price crosses bid', diagnostics={'price': str(price), 'best_bid': str(best_bid)}, validations=[])
                else:  # SELL
                    candidate = best_ask + offset_px
                    px = self._ceil_price_sell(candidate, tick)
                    if px < best_ask:
                        px = self._ceil_price_sell(best_ask + tick, tick)
                    price = px
                    if price < best_ask:
                        return DenyDecision(code='POST_ONLY_BREACH', stage='post_only', reason='sell price crosses ask', diagnostics={'price': str(price), 'best_ask': str(best_ask)}, validations=[])
                # percent price limit check
                if price and mid > 0:
                    deviation_bps = (abs(price - mid) / mid) * Decimal('10000')
                    if deviation_bps > self.percent_price_limit_bps:
                        return DenyDecision(code='PERCENT_PRICE', stage='price_guard', reason='limit deviates too much', diagnostics={'dev_bps': self._int_bps(deviation_bps), 'limit_bps': self._int_bps(self.percent_price_limit_bps)}, validations=[])

            # EdgeBudget components
            fees_comp = (fees_m_comp if route=='maker' else fees_t_comp)
            slip_comp = (Decimal('0') if route=='maker' else slip_t)
            rebates_comp = (rebates_bps if route=='maker' else Decimal('0'))
            # compute net using integer-truncated component bps to align with test expectation
            net_sum = (
                Decimal(str(self._int_bps(raw_edge))) +
                Decimal(str(self._int_bps(fees_comp))) +
                Decimal(str(self._int_bps(slip_comp))) +
                Decimal(str(self._int_bps(adv_sel))) +
                Decimal(str(self._int_bps(lat_cost_bps))) +
                Decimal(str(self._int_bps(rebates_comp)))
            )
            edge_budget = EdgeBudget(
                dir=int(dir_sign),
                raw=self._int_bps(raw_edge),
                fees=self._int_bps(fees_comp),
                slip_est=self._int_bps(slip_comp),
                adv_sel=self._int_bps(adv_sel),
                lat_cost=self._int_bps(lat_cost_bps),
                rebates=self._int_bps(rebates_comp),
                pi_fill_Tsla=float(p_fill),
                T_SLA_ms=int(pred_latency_ms),
                net_after_tca=self._int_bps(net_sum),
                reason=why_code
            )
            # Metrics: observe net_after_tca and route decision
            try:
                METRICS.aurora.observe_edge_net_after_tca_bps(edge_budget.net_after_tca)
                METRICS.aurora.inc_route_decision(route)
                # Optional: observe p_fill histogram if available in metrics
                try:
                    METRICS.aurora_pfill.observe(float(p_fill))  # if added
                except Exception:
                    pass
            except Exception:
                pass
            if edge_budget.net_after_tca <= 0:
                return DenyDecision(code='EDGE_DENY', stage='final', reason='net_after_tca<=0', diagnostics={'net_after_tca': edge_budget.net_after_tca}, validations=[])

            # group/client ids
            h = hashlib.blake2b(f"{intent.intent_id}|{intent.symbol}|{intent.timestamp_ms}".encode(), digest_size=8).hexdigest()
            group_id = h
            client_order_id = f"AUR|{h}|P|0|0"

            plan = RoutedOrderPlan(
                mode=route, order_type='LIMIT' if route=='maker' else 'MARKET',
                qty=str(qty), client_order_id=client_order_id, group_id=group_id,
                tca=edge_budget, sizing=None, governance_state=intent.regime_ctx.get('governance','shadow'),
                xai_trace_id=intent.intent_id, price=str(price) if price is not None else None, bracket_children=None
            )

            # Log decision
            self.event_logger.emit('ROUTER.DECISION', {
                'symbol': intent.symbol,
                'side': side,
                'why_code': why_code,
                'p_fill': float(p_fill),
                'spread_bps': self._int_bps(spread_bps),
                'latency_ms': float(pred_latency_ms),
                'e_maker_expected': e_m_int,
                'e_taker_expected': e_t_int,
                'route': route,
                'capture_eta': float(self.capture_eta),
                'rebate_mode': self.rebate_mode,
                'p_fill_min': float(self.pi_fill_min)
            })
            return plan
        except DenyDecision as d:  # not typical path
            return d
        except Exception as exc:  # safety net
            return DenyDecision(code='INTERNAL_ERROR', stage=stage, reason=str(exc), diagnostics={'exc': type(exc).__name__}, validations=validations)

__all__ = [
    'OrderIntent','EdgeBudget','KellyApplied','RoutedOrderPlan','DenyDecision','MarketSpec','RouterV2'
]
