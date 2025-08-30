from __future__ import annotations

"""
Execution — Router (maker/taker decision with TCA gate)
=======================================================

Decision framework
------------------
Given a side ("buy" or "sell"), current top-of-book, an ex-ante edge estimate
(in bps), and latency, decide whether to route **maker** or **taker** under
SLA and TCA constraints.

Economics (simplified but principled)
-------------------------------------
Let spread_half_bps = 0.5 * (ask - bid)/mid * 1e4. Then

- Taker expected edge (post-latency):
    E_taker = (E_bps - spread_half_bps)  adjusted by latency via κ (SLAGate)

- Maker expected edge:
    E_maker = (E_bps + spread_half_bps) * P_fill  (no immediate latency penalty)

where P_fill is estimated by a Cox hazard model if provided, otherwise uses
`execution.sla.target_fill_prob` (SSOT) or a conservative default (0.6).

We then choose the route that maximizes expected edge **subject to** SLA gate
(taker can be denied by SLA; maker can be denied if P_fill < min threshold).

Notes
-----
- κ (bps/ms) and max latency are enforced by SLAGate.
- This router does not place orders; it decides the route and explains why.
- The caller should feed the result into `execution/exchange/*` connectors.
"""

from dataclasses import dataclass
from typing import Dict, Mapping, Optional, Tuple

from core.config.loader import get_config, ConfigError
from core.execution.exchange.common import Fees
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate


@dataclass
class QuoteSnapshot:
    bid_px: float
    ask_px: float
    bid_sz: float = 0.0
    ask_sz: float = 0.0
    ts_ns: int = 0

    @property
    def mid(self) -> float:
        return 0.5 * (self.bid_px + self.ask_px)

    @property
    def half_spread_bps(self) -> float:
        m = self.mid
        if m <= 0:
            return 0.0
        return (self.ask_px - self.bid_px) / m * 1e4 * 0.5


@dataclass
class RouteDecision:
    route: str  # 'maker' | 'taker' | 'deny'
    e_maker_bps: float
    e_taker_bps: float
    p_fill: float
    reason: str
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    net_e_maker_bps: float = 0.0  # Expected edge after fees
    net_e_taker_bps: float = 0.0  # Expected edge after fees


class Router:
    def __init__(
        self,
        *,
        hazard_model: Optional[CoxPH] = None,
        slagate: Optional[SLAGate] = None,
        min_p_fill: Optional[float] = None,
        fees: Optional[Fees] = None,
        exchange_name: str = "default",
    ) -> None:
        # hazards
        self._haz = hazard_model
        # SLA
        if slagate is None:
            try:
                cfg = get_config()
                max_latency_ms = float(cfg.get("execution.sla.max_latency_ms", 25))
            except (ConfigError, Exception):
                max_latency_ms = 25.0
            slagate = SLAGate(max_latency_ms=max_latency_ms, kappa_bps_per_ms=0.05, min_edge_after_bps=0.0)
        self._sla = slagate
        # min P(fill)
        if min_p_fill is None:
            try:
                cfg = get_config()
                min_p_fill = float(cfg.get("execution.sla.target_fill_prob", 0.6))
            except (ConfigError, Exception):
                min_p_fill = 0.6
        self._min_p = float(min_p_fill)
        # fees
        if fees is None:
            fees = Fees.from_exchange_config(exchange_name)
        self._fees = fees

    # ------------- API -------------

    def decide(
        self,
        *,
        side: str,  # 'buy' or 'sell'
        quote: QuoteSnapshot,
        edge_bps_estimate: float,
        latency_ms: float,
        fill_features: Optional[Mapping[str, float]] = None,
    ) -> RouteDecision:
        """Return a route decision and its rationale.

        Parameters
        ----------
        side : 'buy'|'sell' (affects sign conventions if you extend E_bps)
        quote: current top of book
        edge_bps_estimate: ex-ante expected edge in bps (positive is favorable)
        latency_ms: measured decision→exchange latency
        fill_features: optional features for P(fill) via CoxPH
        """
        half = quote.half_spread_bps
        E = float(edge_bps_estimate)

        # taker: pay half-spread + taker fee
        e_taker_pre = E - half - self._fees.taker_fee_bps
        # apply SLA (latency, post-latency edge floor)
        sla_res = self._sla.gate(edge_bps=e_taker_pre, latency_ms=latency_ms)
        e_taker = sla_res.edge_after_bps

        # maker: earn half-spread if filled, minus maker fee (or plus rebate if negative)
        p_fill = self._estimate_p_fill(fill_features)
        e_maker = (E + half - self._fees.maker_fee_bps) * p_fill

        # Calculate net expected edges (after fees)
        net_e_taker = e_taker
        net_e_maker = e_maker

        # hard constraints
        if p_fill < self._min_p and (e_taker > 0.0 or sla_res.allow):
            return RouteDecision(
                route="taker" if sla_res.allow else "deny",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"P(fill) {p_fill:.2f} < min {self._min_p:.2f}; taker {'allowed' if sla_res.allow else 'denied'}",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=net_e_maker,
                net_e_taker_bps=net_e_taker,
            )

        # If SLA denies taker, fallback to maker if e_maker positive and p_fill ok
        if not sla_res.allow:
            if e_maker > 0.0 and p_fill >= self._min_p:
                return RouteDecision(
                    route="maker",
                    e_maker_bps=e_maker,
                    e_taker_bps=e_taker,
                    p_fill=p_fill,
                    reason=f"SLA denied taker, fallback to maker (E_maker={e_maker:.2f}bps, Pfill={p_fill:.2f})",
                    maker_fee_bps=self._fees.maker_fee_bps,
                    taker_fee_bps=self._fees.taker_fee_bps,
                    net_e_maker_bps=net_e_maker,
                    net_e_taker_bps=net_e_taker,
                )
            return RouteDecision(
                route="deny",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"SLA denied taker and maker unattractive (E_maker={e_maker:.2f}bps, Pfill={p_fill:.2f})",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=net_e_maker,
                net_e_taker_bps=net_e_taker,
            )

        # Both routes allowed: choose higher expected value
        if e_taker >= e_maker and e_taker > 0.0:
            return RouteDecision(
                route="taker",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"E_taker {e_taker:.2f} ≥ E_maker {e_maker:.2f}; SLA OK",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=net_e_maker,
                net_e_taker_bps=net_e_taker,
            )
        if e_maker > 0.0 and p_fill >= self._min_p:
            return RouteDecision(
                route="maker",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"E_maker {e_maker:.2f} > E_taker {e_taker:.2f}; Pfill {p_fill:.2f} ≥ {self._min_p:.2f}",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=net_e_maker,
                net_e_taker_bps=net_e_taker,
            )

        # None attractive
        decision = RouteDecision(
            route="deny",
            e_maker_bps=e_maker,
            e_taker_bps=e_taker,
            p_fill=p_fill,
            reason=f"Both routes unattractive (E_taker={e_taker:.2f}bps, E_maker={e_maker:.2f}bps)",
            maker_fee_bps=self._fees.maker_fee_bps,
            taker_fee_bps=self._fees.taker_fee_bps,
            net_e_maker_bps=net_e_maker,
            net_e_taker_bps=net_e_taker,
        )
        
        # XAI logging
        why_code = "WHY_UNATTRACTIVE"
        if decision.route == "taker":
            why_code = "OK_ROUTE_TAKER"
        elif decision.route == "maker":
            why_code = "OK_ROUTE_MAKER"
        elif not sla_res.allow:
            why_code = "WHY_SLA_DENY"
        elif p_fill < self._min_p:
            why_code = "WHY_LOW_PFILL"
        
        # Log the routing decision (skip decision validation)
        log_entry = {
            "event_type": "ROUTE_DECISION",
            "timestamp_ns": 0,  # Would be set by logger
            "symbol": "",  # Would be passed in from caller
            "why_code": why_code,
            "inputs": {
                "side": side,
                "edge_bps_estimate": edge_bps_estimate,
                "latency_ms": latency_ms,
                "half_spread_bps": half,
                "p_fill": p_fill,
                "min_p_fill": self._min_p,
                "maker_fee_bps": self._fees.maker_fee_bps,
                "taker_fee_bps": self._fees.taker_fee_bps
            },
            "outputs": {
                "route": decision.route,
                "e_maker_bps": decision.e_maker_bps,
                "e_taker_bps": decision.e_taker_bps,
                "net_e_maker_bps": decision.net_e_maker_bps,
                "net_e_taker_bps": decision.net_e_taker_bps,
                "reason": decision.reason
            }
        }
        
        # Simple file logging for routing events
        import json
        from pathlib import Path
        log_path = Path("logs/routing_decisions.jsonl")
        log_path.parent.mkdir(exist_ok=True)
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry, separators=(",", ":")) + "\n")
        
        return decision

    # ------------- internals -------------

    def _estimate_p_fill(self, feats: Optional[Mapping[str, float]]) -> float:
        # Default: SSOT target_fill_prob; hazard model if provided
        if self._haz is None or feats is None:
            try:
                cfg = get_config()
                return float(cfg.get("execution.sla.target_fill_prob", 0.6))
            except (ConfigError, Exception):
                return 0.6

        # Use proper Cox model survival curve
        try:
            cfg = get_config()
            horizon_ms = float(cfg.get("execution.router.horizon_ms", 1000.0))  # 1 second default
        except (ConfigError, Exception):
            horizon_ms = 1000.0
        
        return self._haz.p_fill(horizon_ms, feats)
        

__all__ = ["QuoteSnapshot", "RouteDecision", "Router"]
