import warnings

warnings.warn(
    "core.execution.router is archived; use core.execution.router_v2.RouterV2",
    DeprecationWarning,
    stacklevel=2,
)
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Union


@dataclass
class Decision:
    route: str  # "maker" | "taker" | "deny"
    why_code: str  # e.g. "OK_ROUTE_MAKER", "OK_ROUTE_TAKER", "WHY_UNATTRACTIVE", "WHY_SLA_LATENCY"
    scores: Dict[str, float]
    e_maker_bps: float = 0.0
    e_taker_bps: float = 0.0
    p_fill: float = 0.0
    reason: Optional[str] = None
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    net_e_maker_bps: float = 0.0
    net_e_taker_bps: float = 0.0


@dataclass
class QuoteSnapshot:
    bid_px: float
    ask_px: float
    bid_sz: Optional[float] = None
    ask_sz: Optional[float] = None

    @property
    def half_spread_bps(self) -> float:
        mid = (self.bid_px + self.ask_px) / 2.0
        if mid <= 0:
            return 0.0
        half_spread = (self.ask_px - self.bid_px) / 2.0
        return (half_spread / mid) * 10000.0


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _estimate_p_fill(fill_features: Dict[str, Any]) -> float:
    obi = float(fill_features.get("obi", 0.0))
    spread_bps = float(fill_features.get("spread_bps", 0.0))
    p = 0.5 + 0.5 * obi - 0.05 * spread_bps
    return _clip01(p)


class XaiLogger:
    def __init__(self, log_file=None):
        self.log_file = log_file

    def log_decision(self, event_type: str, data: Dict[str, Any]):
        if self.log_file:
            log_entry = {"event_type": event_type, "timestamp": time.time(), **data}
            with open(self.log_file, "a") as f:
                f.write(json.dumps(log_entry) + "\n")


class Router:
    def __init__(
        self,
        cfg: Dict[str, Any] = None,
        hazard_model=None,
        slagate=None,
        min_p_fill: float = 0.25,
        exchange_name: str = None,
        xai_logger=None,
    ):
        if hazard_model or slagate:
            self._init_from_modules(hazard_model, slagate, min_p_fill, exchange_name)
        else:
            self._init_from_config(cfg or {})

        self.xai_logger = xai_logger or XaiLogger()

    def _init_from_config(self, cfg: Dict[str, Any]):
        ex = cfg.get("execution", {})
        r = ex.get("router", {})
        sla = ex.get("sla", {})

        self.edge_floor_bps: float = float(ex.get("edge_floor_bps", 0.0))
        self.p_min_fill: float = float(r.get("p_min_fill", 0.25))
        self.horizon_ms: int = int(r.get("horizon_ms", 1500))
        self.kappa_bps_per_ms: float = float(sla.get("kappa_bps_per_ms", 0.0))
        self.max_latency_ms: float = float(sla.get("max_latency_ms", float("inf")))

        self.spread_deny_bps: float = float(r.get("spread_deny_bps", 8.0))
        self.maker_spread_ok_bps: float = float(r.get("maker_spread_ok_bps", 2.0))
        self.switch_margin_bps: float = float(r.get("switch_margin_bps", 0.0))

    def _init_from_modules(
        self, hazard_model, slagate, min_p_fill: float, exchange_name: str
    ):
        self.hazard_model = hazard_model
        self.slagate = slagate
        self.p_min_fill = min_p_fill
        self.exchange_name = exchange_name

        self.edge_floor_bps = 1.0
        self.horizon_ms = 1500
        self.kappa_bps_per_ms = 0.01
        self.max_latency_ms = 250.0
        self.spread_deny_bps = 8.0
        self.maker_spread_ok_bps = 2.0
        self.switch_margin_bps = 0.0

    def decide(
        self,
        side: str,
        quote: Union[QuoteSnapshot, Any],
        edge_bps_estimate: float = None,
        latency_ms: float = None,
        fill_features: Dict[str, Any] = None,
    ) -> Decision:
        if fill_features is None:
            fill_features = {}
        if edge_bps_estimate is None:
            edge_bps_estimate = 2.0
        if latency_ms is None:
            latency_ms = 10.0

        if hasattr(self, "slagate") and self.slagate:
            slagate_result = self.slagate.gate(
                edge_bps=edge_bps_estimate, latency_ms=latency_ms
            )
            if not slagate_result.allow:
                decision = Decision(
                    route="deny",
                    why_code="WHY_SLA_LATENCY",
                    scores={
                        "latency_ms": float(latency_ms),
                        "max_latency_ms": self.slagate.max_latency_ms,
                        "edge_after_bps": slagate_result.edge_after_bps,
                    },
                )
                self.xai_logger.log_decision(
                    "SLA_DENY",
                    {
                        "why_code": "WHY_SLA_LATENCY",
                        "latency_ms": latency_ms,
                        "max_latency_ms": self.slagate.max_latency_ms,
                        "side": side,
                    },
                )
                return decision
        elif latency_ms > self.max_latency_ms:
            decision = Decision(
                route="deny",
                why_code="WHY_SLA_LATENCY",
                scores={
                    "latency_ms": float(latency_ms),
                    "max_latency_ms": self.max_latency_ms,
                },
            )
            self.xai_logger.log_decision(
                "SLA_DENY",
                {
                    "why_code": "WHY_SLA_LATENCY",
                    "latency_ms": latency_ms,
                    "max_latency_ms": self.max_latency_ms,
                    "side": side,
                },
            )
            return decision

        edge_after_lat = float(edge_bps_estimate) - self.kappa_bps_per_ms * float(
            latency_ms
        )

        spread_bps = float(fill_features.get("spread_bps", 2.0))
        if spread_bps >= self.spread_deny_bps:
            decision = Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                    "spread_bps": spread_bps,
                    "spread_deny_bps": self.spread_deny_bps,
                },
            )
            self.xai_logger.log_decision(
                "SPREAD_DENY",
                {
                    "why_code": "WHY_UNATTRACTIVE",
                    "spread_bps": spread_bps,
                    "spread_deny_bps": self.spread_deny_bps,
                    "side": side,
                },
            )
            return decision

        if edge_after_lat < self.edge_floor_bps:
            decision = Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                },
            )
            self.xai_logger.log_decision(
                "EDGE_FLOOR_DENY",
                {
                    "why_code": "WHY_UNATTRACTIVE",
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                    "side": side,
                },
            )
            return decision

        p_fill = _estimate_p_fill(fill_features)
        e_maker_base = edge_after_lat
        e_taker_base = edge_after_lat - (spread_bps / 2.0)
        e_maker_expected = e_maker_base * p_fill
        e_taker_expected = e_taker_base
        maker_viable = (p_fill >= self.p_min_fill) and (
            spread_bps <= self.maker_spread_ok_bps
        )
        prefer_maker = maker_viable and (e_maker_expected >= e_taker_expected)

        if prefer_maker:
            decision = Decision(
                route="maker",
                why_code="OK_ROUTE_MAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "maker_spread_ok_bps": self.maker_spread_ok_bps,
                    "edge_after_latency_bps": edge_after_lat,
                    "e_maker_expected": e_maker_expected,
                    "e_taker_expected": e_taker_expected,
                },
            )
            self.xai_logger.log_decision(
                "ROUTE_MAKER",
                {
                    "why_code": "OK_ROUTE_MAKER",
                    "p_fill": p_fill,
                    "spread_bps": spread_bps,
                    "edge_after_latency_bps": edge_after_lat,
                    "side": side,
                },
            )
            return decision
        else:
            decision = Decision(
                route="taker",
                why_code="OK_ROUTE_TAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "edge_after_latency_bps": edge_after_lat,
                },
            )
            self.xai_logger.log_decision(
                "ROUTE_TAKER",
                {
                    "why_code": "OK_ROUTE_TAKER",
                    "p_fill": p_fill,
                    "spread_bps": spread_bps,
                    "edge_after_latency_bps": edge_after_lat,
                    "side": side,
                },
            )
            return decision
