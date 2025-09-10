from dataclasses import dataclass
from typing import Any


@dataclass
class Decision:
    route: str                 # "maker" | "taker" | "deny"
    why_code: str              # e.g. "OK_ROUTE_MAKER", "OK_ROUTE_TAKER", "WHY_UNATTRACTIVE", "WHY_SLA_LATENCY"
    scores: dict[str, float]


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _estimate_p_fill(fill_features: dict[str, Any]) -> float:
    """
    Простий, детермінований естіматор P(fill) із ознак:
    - OBI in [-1,1] збільшує P
    - spread_bps зменшує P (5 bps ~ -0.25 до P)
    """
    obi = float(fill_features.get("obi", 0.0))
    spread_bps = float(fill_features.get("spread_bps", 0.0))
    p = 0.5 + 0.5 * obi - 0.05 * spread_bps
    return _clip01(p)


class Router:
    """
    Router v1.1 для інтеграційних тестів
    
    Конфіг очікується такого вигляду (див. інтеграційний тест):
      execution:
        edge_floor_bps: 1.0
        router: { horizon_ms: 1500, p_min_fill: 0.25 }
        sla:    { kappa_bps_per_ms: 0.01, max_latency_ms: 250 }

    Додатково вводимо:
        router.spread_deny_bps (def=8.0)
        router.maker_spread_ok_bps (def=2.0) — для схилення у maker при tight spread
        router.switch_margin_bps (def=0.0)
    """

    def __init__(self, cfg: dict[str, Any]):
        ex = (cfg or {}).get("execution", {})
        r = (ex or {}).get("router", {})
        sla = (ex or {}).get("sla", {})

        self.edge_floor_bps: float = float(ex.get("edge_floor_bps", 0.0))
        self.p_min_fill: float = float(r.get("p_min_fill", 0.25))
        self.horizon_ms: int = int(r.get("horizon_ms", 1500))
        self.kappa_bps_per_ms: float = float(sla.get("kappa_bps_per_ms", 0.0))
        self.max_latency_ms: float = float(sla.get("max_latency_ms", float("inf")))

        # додаткові пороги
        self.spread_deny_bps: float = float(r.get("spread_deny_bps", 8.0))
        self.maker_spread_ok_bps: float = float(r.get("maker_spread_ok_bps", 2.0))
        self.switch_margin_bps: float = float(r.get("switch_margin_bps", 0.0))

    def decide(self,
               side: str,
               quote,                       # QuoteSnapshot із bid/ask
               edge_bps_estimate: float,
               latency_ms: float,
               fill_features: dict[str, Any]) -> Decision:

        # 1) SLA gate — надмірна латентність
        if latency_ms > self.max_latency_ms:
            return Decision(
                route="deny",
                why_code="WHY_SLA_LATENCY",
                scores={
                    "latency_ms": float(latency_ms),
                    "max_latency_ms": self.max_latency_ms
                }
            )

        # 2) Штраф за латентність -> edge_after_latency
        edge_after_lat = float(edge_bps_estimate) - self.kappa_bps_per_ms * float(latency_ms)

        # 3) Gate на надто широкий спред (ринок «непривабливий» для будь-якого маршруту)
        spread_bps = float(fill_features.get("spread_bps", 0.0))
        if spread_bps >= self.spread_deny_bps:
            return Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                    "spread_bps": spread_bps,
                    "spread_deny_bps": self.spread_deny_bps
                }
            )

        # 4) Edge floor після latency
        if edge_after_lat < self.edge_floor_bps:
            return Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps
                }
            )

        # 5) Вибір maker/taker за очікуваною вигодою з P(fill)
        p_fill = _estimate_p_fill(fill_features)
        # Проста правило: якщо заповнюваність висока і спред «tight» — maker; інакше taker.
        prefer_maker = (p_fill >= max(self.p_min_fill, 0.5)) and (spread_bps <= self.maker_spread_ok_bps)

        # Для стабільності — switch_margin: якщо близько до межі, не переключаємося
        # (тут використано як поріг на p_fill, edge прирівнюємо)
        if prefer_maker:
            return Decision(
                route="maker",
                why_code="OK_ROUTE_MAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "maker_spread_ok_bps": self.maker_spread_ok_bps,
                    "edge_after_latency_bps": edge_after_lat
                }
            )
        else:
            return Decision(
                route="taker",
                why_code="OK_ROUTE_TAKER",
                scores={
                    "p_fill": p_fill,
                    "p_min_fill": self.p_min_fill,
                    "spread_bps": spread_bps,
                    "edge_after_latency_bps": edge_after_lat
                }
            )
