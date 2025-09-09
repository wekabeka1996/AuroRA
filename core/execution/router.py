import warnings
warnings.warn("core.execution.router is deprecated; use core.execution.router_v2.RouterV2", DeprecationWarning, stacklevel=2)
from dataclasses import dataclass
from typing import Optional, Dict, Any, Union
import json
import time


@dataclass
class Decision:
    route: str                 # "maker" | "taker" | "deny"
    why_code: str              # e.g. "OK_ROUTE_MAKER", "OK_ROUTE_TAKER", "WHY_UNATTRACTIVE", "WHY_SLA_LATENCY"
    scores: Dict[str, float]
    # Backwards-compatible optional fields used by older callers/tests
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
    """Snapshot of bid/ask prices for routing decisions."""
    bid_px: float
    ask_px: float
    bid_sz: Optional[float] = None
    ask_sz: Optional[float] = None
    
    @property
    def half_spread_bps(self) -> float:
        """Half-spread in basis points."""
        mid = (self.bid_px + self.ask_px) / 2.0
        if mid <= 0:
            return 0.0
        half_spread = (self.ask_px - self.bid_px) / 2.0
        return (half_spread / mid) * 10000.0  # Convert to bps


# Backwards-compatible alias used by some tests
from typing import Optional as _Optional, Dict as _Dict


@dataclass
class RouteDecision:
    route: str  # 'maker' | 'taker' | 'deny'
    e_maker_bps: float
    e_taker_bps: float
    p_fill: float
    reason: str
    maker_fee_bps: float = 0.0
    taker_fee_bps: float = 0.0
    net_e_maker_bps: float = 0.0
    net_e_taker_bps: float = 0.0
    scores: _Optional[_Dict[str, float]] = None
    
    # P3-α Governance fields
    sprt_llr: _Optional[float] = None         # SPRT log-likelihood ratio
    sprt_conf: _Optional[float] = None        # SPRT decision confidence [0,1]
    alpha_spent: _Optional[float] = None      # α budget spent on this decision


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else x)


def _estimate_p_fill(fill_features: Dict[str, Any]) -> float:
    """
    Простий, детермінований естіматор P(fill) із ознак:
    - OBI in [-1,1] збільшує P
    - spread_bps зменшує P (5 bps ~ -0.25 до P)
    """
    obi = float(fill_features.get("obi", 0.0))
    spread_bps = float(fill_features.get("spread_bps", 0.0))
    p = 0.5 + 0.5 * obi - 0.05 * spread_bps
    return _clip01(p)


class XaiLogger:
    """Mock XAI logger for decision explanations."""
    
    def __init__(self, log_file=None):
        self.log_file = log_file
        
    def log_decision(self, event_type: str, data: Dict[str, Any]):
        """Log decision with explanation."""
        if self.log_file:
            log_entry = {
                "event_type": event_type,
                "timestamp": time.time(),
                **data
            }
            with open(self.log_file, 'a') as f:
                f.write(json.dumps(log_entry) + '\n')


class Router:
    """
    Router v1.1 для інтеграційних тестів з XAI підтримкою
    
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
    
    def __init__(self, cfg: Dict[str, Any] = None, hazard_model=None, slagate=None, 
                 min_p_fill: float = 0.25, exchange_name: str = None, xai_logger=None):
        """Ініціалізація Router з підтримкою різних API."""
        # Backward compatibility - підтримка старого API з модулями
        if hazard_model or slagate:
            self._init_from_modules(hazard_model, slagate, min_p_fill, exchange_name)
        else:
            self._init_from_config(cfg or {})
            
        self.xai_logger = xai_logger or XaiLogger()

    def _init_from_config(self, cfg: Dict[str, Any]):
        """Ініціалізація з конфігу."""
        ex = cfg.get("execution", {})
        r = ex.get("router", {})
        sla = ex.get("sla", {})
        
        self.edge_floor_bps: float = float(ex.get("edge_floor_bps", 0.0))
        self.p_min_fill: float = float(r.get("p_min_fill", 0.25))
        self.horizon_ms: int = int(r.get("horizon_ms", 1500))
        self.kappa_bps_per_ms: float = float(sla.get("kappa_bps_per_ms", 0.0))
        self.max_latency_ms: float = float(sla.get("max_latency_ms", float("inf")))
        
        # додаткові пороги
        self.spread_deny_bps: float = float(r.get("spread_deny_bps", 8.0))
        self.maker_spread_ok_bps: float = float(r.get("maker_spread_ok_bps", 2.0))
        self.switch_margin_bps: float = float(r.get("switch_margin_bps", 0.0))

    def _init_from_modules(self, hazard_model, slagate, min_p_fill: float, exchange_name: str):
        """Ініціалізація з окремих модулів (backward compatibility)."""
        self.hazard_model = hazard_model
        self.slagate = slagate
        self.p_min_fill = min_p_fill
        self.exchange_name = exchange_name
        
        # Default values for compatibility
        self.edge_floor_bps = 1.0  # Keep original backward compatibility default
        self.horizon_ms = 1500
        self.kappa_bps_per_ms = 0.01
        self.max_latency_ms = 250.0
        self.spread_deny_bps = 8.0
        self.maker_spread_ok_bps = 2.0
        self.switch_margin_bps = 0.0

    def decide(self,
               side: str,
               quote: Union[QuoteSnapshot, Any],                       
               edge_bps_estimate: float = None,
               latency_ms: float = None,
               fill_features: Dict[str, Any] = None) -> Union[Decision, Any]:
        """
        Універсальний метод decide з підтримкою обох API:
        - Новий API: повертає Decision з route/why_code/scores
        - Старий API: повертає об'єкт з route/reason/p_fill для сумісності
        """
        # Нормалізація параметрів
        if fill_features is None:
            fill_features = {}
        if edge_bps_estimate is None:
            edge_bps_estimate = 2.0  # default
        if latency_ms is None:
            latency_ms = 10.0  # default
            
        # 1) SLA gate — надмірна латентність
        if hasattr(self, 'slagate') and self.slagate:
            # Use slagate for latency check in backward compatibility mode
            slagate_result = self.slagate.gate(edge_bps=edge_bps_estimate, latency_ms=latency_ms)
            if not slagate_result.allow:
                decision = Decision(
                    route="deny",
                    why_code="WHY_SLA_LATENCY",
                    scores={
                        "latency_ms": float(latency_ms),
                        "max_latency_ms": self.slagate.max_latency_ms,
                        "edge_after_bps": slagate_result.edge_after_bps
                    }
                )
                
                # XAI логування
                self.xai_logger.log_decision("SLA_DENY", {
                    "why_code": "WHY_SLA_LATENCY",
                    "latency_ms": latency_ms,
                    "max_latency_ms": self.slagate.max_latency_ms,
                    "side": side
                })
                
                # Backward compatibility
                if hasattr(self, 'hazard_model'):
                    return Decision(
                        route='deny',
                        why_code='WHY_SLA_LATENCY',
                        scores={
                            'latency_ms': float(latency_ms),
                            'max_latency_ms': self.slagate.max_latency_ms
                        },
                        e_maker_bps=0.0,
                        e_taker_bps=0.0,
                        p_fill=0.0,
                        reason=slagate_result.reason
                    )

                return decision
        elif latency_ms > self.max_latency_ms:
            decision = Decision(
                route="deny",
                why_code="WHY_SLA_LATENCY",
                scores={
                    "latency_ms": float(latency_ms),
                    "max_latency_ms": self.max_latency_ms
                }
            )
            
            # XAI логування
            self.xai_logger.log_decision("SLA_DENY", {
                "why_code": "WHY_SLA_LATENCY",
                "latency_ms": latency_ms,
                "max_latency_ms": self.max_latency_ms,
                "side": side
            })
            
            # Backward compatibility - return Decision-compatible object for legacy consumers
            if hasattr(self, 'hazard_model'):
                return Decision(
                    route='deny',
                    why_code='WHY_SLA_LATENCY',
                    scores={
                        'latency_ms': float(latency_ms),
                        'max_latency_ms': self.max_latency_ms
                    },
                    e_maker_bps=0.0,
                    e_taker_bps=0.0,
                    p_fill=0.0,
                    reason='SLA denied - latency too high'
                )

            return decision

        # 2) Штраф за латентність -> edge_after_latency
        edge_after_lat = float(edge_bps_estimate) - self.kappa_bps_per_ms * float(latency_ms)

        # 3) Gate на надто широкий спред (ринок «непривабливий» для будь-якого маршруту)
        spread_bps = float(fill_features.get("spread_bps", 2.0))
        if spread_bps >= self.spread_deny_bps:
            decision = Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps,
                    "spread_bps": spread_bps,
                    "spread_deny_bps": self.spread_deny_bps
                }
            )
            
            # XAI логування
            self.xai_logger.log_decision("SPREAD_DENY", {
                "why_code": "WHY_UNATTRACTIVE",
                "spread_bps": spread_bps,
                "spread_deny_bps": self.spread_deny_bps,
                "side": side
            })
            
            # Backward compatibility
            if hasattr(self, 'hazard_model'):
                return Decision(
                    route='deny',
                    why_code='WHY_UNATTRACTIVE',
                    scores={
                        'edge_after_latency_bps': edge_after_lat,
                        'edge_floor_bps': self.edge_floor_bps,
                        'spread_bps': spread_bps,
                        'spread_deny_bps': self.spread_deny_bps
                    },
                    e_maker_bps=0.0,
                    e_taker_bps=0.0,
                    p_fill=0.0,
                    reason='Market unattractive - spread too wide'
                )

            return decision

        # 4) Edge floor після latency
        if edge_after_lat < self.edge_floor_bps:
            decision = Decision(
                route="deny",
                why_code="WHY_UNATTRACTIVE",
                scores={
                    "edge_after_latency_bps": edge_after_lat,
                    "edge_floor_bps": self.edge_floor_bps
                }
            )
            
            # XAI логування
            self.xai_logger.log_decision("EDGE_FLOOR_DENY", {
                "why_code": "WHY_UNATTRACTIVE",
                "edge_after_latency_bps": edge_after_lat,
                "edge_floor_bps": self.edge_floor_bps,
                "side": side
            })
            
            # Backward compatibility
            if hasattr(self, 'hazard_model'):
                return Decision(
                    route='deny',
                    why_code='WHY_UNATTRACTIVE',
                    scores={
                        'edge_after_latency_bps': edge_after_lat,
                        'edge_floor_bps': self.edge_floor_bps
                    },
                    e_maker_bps=0.0,
                    e_taker_bps=0.0,
                    p_fill=0.0,
                    reason='Market unattractive - edge too low'
                )

            return decision

        # 5) Вибір maker/taker за очікуваною вигодою з P(fill)
        p_fill = _estimate_p_fill(fill_features)
        
        # Розрахунок очікуваних вигод
        # e_maker = edge_after_lat (тільки якщо заповниться)
        # e_taker = edge_after_lat - spread/2 (миттєво заповниться)
        e_maker_base = edge_after_lat
        e_taker_base = edge_after_lat - (spread_bps / 2.0)
        
        # Вибір на основі очікуваних вигод (з урахуванням p_fill для maker)
        e_maker_expected = e_maker_base * p_fill  # очікувана вигода maker з ймовірністю заповнення
        e_taker_expected = e_taker_base  # taker завжди заповнюється
        
        # Також перевіряємо мінімальні пороги
        maker_viable = (p_fill >= self.p_min_fill) and (spread_bps <= self.maker_spread_ok_bps)
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
                    "e_taker_expected": e_taker_expected
                }
            )
            
            # XAI логування
            self.xai_logger.log_decision("ROUTE_MAKER", {
                "why_code": "OK_ROUTE_MAKER",
                "p_fill": p_fill,
                "spread_bps": spread_bps,
                "edge_after_latency_bps": edge_after_lat,
                "side": side
            })
            
            # Backward compatibility
            if hasattr(self, 'hazard_model'):
                return Decision(
                    route='maker',
                    why_code='OK_ROUTE_MAKER',
                    scores={
                        'p_fill': p_fill,
                        'p_min_fill': self.p_min_fill,
                        'spread_bps': spread_bps,
                        'maker_spread_ok_bps': self.maker_spread_ok_bps,
                        'edge_after_latency_bps': edge_after_lat
                    },
                    e_maker_bps=e_maker_expected,  # Use expected value, not base
                    e_taker_bps=e_taker_expected,  # Use expected value, not base
                    p_fill=p_fill,
                    reason='E_maker > E_taker'
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
                    "edge_after_latency_bps": edge_after_lat
                }
            )
            
            # XAI логування
            self.xai_logger.log_decision("ROUTE_TAKER", {
                "why_code": "OK_ROUTE_TAKER",
                "p_fill": p_fill,
                "spread_bps": spread_bps,
                "edge_after_latency_bps": edge_after_lat,
                "side": side
            })
            
            # Backward compatibility
            if hasattr(self, 'hazard_model'):
                return Decision(
                    route='taker',
                    why_code='OK_ROUTE_TAKER',
                    scores={
                        'p_fill': p_fill,
                        'p_min_fill': self.p_min_fill,
                        'spread_bps': spread_bps,
                        'edge_after_latency_bps': edge_after_lat
                    },
                    e_maker_bps=e_maker_expected,  # Use expected value, not base
                    e_taker_bps=e_taker_expected,  # Use expected value, not base
                    p_fill=p_fill,
                    reason='E_taker > E_maker'
                )

            return decision