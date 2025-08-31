from __future__ import annotations

from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    features: List[float]


class PredictionResponse(BaseModel):
    forecast: float
    interval_lower: float
    interval_upper: float
    weights: List[float]
    kappa_plus: float
    regime: int
    latency_ms: float


class AccountInfo(BaseModel):
    # Розширювано при потребі; зараз використовуємо тільки режим роботи раннера
    mode: Optional[str] = None  # 'paper' | 'prod'  (historical 'shadow' mode removed)
    account_id: Optional[str] = None
    subaccount: Optional[str] = None


class OrderInfo(BaseModel):
    symbol: Optional[str] = None
    side: Optional[str] = None  # 'buy' | 'sell'
    qty: Optional[float] = None
    price: Optional[float] = None
    base_notional: Optional[float] = None
    notional: Optional[float] = None


class MarketInfo(BaseModel):
    # Латентність/ринкові метрики
    latency_ms: Optional[float] = None
    slip_bps_est: Optional[float] = None
    a_bps: Optional[float] = None
    b_bps: Optional[float] = None
    spread_bps: Optional[float] = None
    # Альфа/режим
    score: Optional[float] = None
    mode_regime: Optional[str] = None
    # TRAP
    trap_cancel_deltas: Optional[List[float]] = None
    trap_add_deltas: Optional[List[float]] = None
    trap_trades_cnt: Optional[int] = None
    obi_sign: Optional[int] = None
    tfi_sign: Optional[int] = None
    # SPRT
    sprt_samples: Optional[List[float]] = None
    # Risk context
    pnl_today_pct: Optional[float] = None
    open_positions: Optional[int] = None


class PretradeCheckRequest(BaseModel):
    ts: Optional[int] = None
    req_id: Optional[str] = None
    account: AccountInfo | Dict[str, Any]
    order: OrderInfo | Dict[str, Any]
    market: MarketInfo | Dict[str, Any]
    risk_tags: Optional[List[str]] = None
    fees_bps: Optional[float] = None


class PretradeCheckResponse(BaseModel):
    allow: bool
    max_qty: float
    risk_scale: Optional[float] = Field(default=1.0, ge=0.0, le=1.0)
    cooldown_ms: int = 0
    reason: str = "ok"
    hard_gate: bool = False
    quotas: Optional[Dict[str, Any]] = None
    observability: Dict[str, Any]
