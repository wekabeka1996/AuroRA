import warnings

warnings.warn(
    "core.execution.router_new is archived; use core.execution.router_v2.RouterV2",
    DeprecationWarning,
    stacklevel=2,
)
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class Decision:
    route: str  # "maker" | "taker" | "deny"
    why_code: str  # e.g. "OK_ROUTE_MAKER", "OK_ROUTE_TAKER", "WHY_UNATTRACTIVE", "WHY_SLA_LATENCY"
    scores: Dict[str, float]


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _estimate_p_fill(fill_features: Dict[str, Any]) -> float:
    obi = float(fill_features.get("obi", 0.0))
    spread_bps = float(fill_features.get("spread_bps", 0.0))
    p = 0.5 + 0.5 * obi - 0.05 * spread_bps
    return _clip01(p)


class Router:
    def __init__(self, cfg: Dict[str, Any]):
        ex = (cfg or {}).get("execution", {})
        r = (ex or {}).get("router", {})
        sla = (ex or {}).get("sla", {})

        self.edge_floor_bps: float = float(ex.get("edge_floor_bps", 0.0))
        self.p_min_fill: float = float(r.get("p_min_fill", 0.25))
        self.horizon_ms: int = int(r.get("horizon_ms", 1500))
        self.kappa_bps_per_ms: float = float(sla.get("kappa_bps_per_ms", 0.0))
        self.max_latency_ms: float = float(sla.get("max_latency_ms", float("inf")))

        self.spread_deny_bps: float = float(r.get("spread_deny_bps", 8.0))
        self.maker_spread_ok_bps: float = float(r.get("maker_spread_ok_bps", 2.0))
        self.switch_margin_bps: float = float(r.get("switch_margin_bps", 0.0))

    def decide(
        self,
        side: str,
        quote,  # QuoteSnapshot із bid/ask
        edge_bps_estimate: float,
        latency_ms: float,
        fill_features: Dict[str, Any],
    ) -> Decision:

        if latency_ms > self.max_latency_ms:
            return Decision(
                route="deny",
                why_code="WHY_SLA_LATENCY",
                scores={
                    "latency_ms": float(latency_ms),
                    "max_latency_ms": self.max_latency_ms,
                },
            )

        edge_after_lat = float(edge_bps_estimate) - self.kappa_bps_per_ms * float(
            latency_ms
        )

        spread_bps = float(fill_features.get("spread_bps", 0.0))
        if spread_bps >= self.spread_deny_bps:
            return Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                    "spread_bps": spread_bps,
                    "spread_deny_bps": self.spread_deny_bps,
                },
            )

        if edge_after_lat < self.edge_floor_bps:
            return Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                },
            )

        p_fill = _estimate_p_fill(fill_features)
        prefer_maker = (p_fill >= max(self.p_min_fill, 0.5)) and (
            spread_bps <= self.maker_spread_ok_bps
        )

        if prefer_maker:
            return Decision(
                route="maker",
                why_code="OK_ROUTE_MAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "maker_spread_ok_bps": self.maker_spread_ok_bps,
                    "edge_after_latency_bps": edge_after_lat,
                },
            )
        else:
            return Decision(
                route="taker",
                why_code="OK_ROUTE_TAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "edge_after_latency_bps": edge_after_lat,
                },
            )
