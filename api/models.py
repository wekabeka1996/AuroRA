from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    features: list[float]


class PredictionResponse(BaseModel):
    forecast: float
    interval_lower: float
    interval_upper: float
    weights: list[float]
    kappa_plus: float
    regime: int
    latency_ms: float


class AccountInfo(BaseModel):
    # Розширювано при потребі; зараз використовуємо тільки режим роботи раннера
    mode: str | None = None  # 'paper' | 'prod'  (historical 'shadow' mode removed)
    account_id: str | None = None
    subaccount: str | None = None


class OrderInfo(BaseModel):
    symbol: str | None = None
    side: str | None = None  # 'buy' | 'sell'
    qty: float | None = None
    price: float | None = None
    base_notional: float | None = None
    notional: float | None = None


class MarketInfo(BaseModel):
    # Латентність/ринкові метрики
    latency_ms: float | None = None
    slip_bps_est: float | None = None
    a_bps: float | None = None
    b_bps: float | None = None
    spread_bps: float | None = None
    # Альфа/режим
    score: float | None = None
    mode_regime: str | None = None
    # TRAP
    trap_cancel_deltas: list[float] | None = None
    trap_add_deltas: list[float] | None = None
    trap_trades_cnt: int | None = None
    obi_sign: int | None = None
    tfi_sign: int | None = None
    # SPRT
    sprt_samples: list[float] | None = None
    # Risk context
    pnl_today_pct: float | None = None
    open_positions: int | None = None


class PretradeCheckRequest(BaseModel):
    ts: int | None = None
    req_id: str | None = None
    account: AccountInfo | dict[str, Any]
    order: OrderInfo | dict[str, Any]
    market: MarketInfo | dict[str, Any]
    risk_tags: list[str] | None = None
    fees_bps: float | None = None


class PretradeCheckResponse(BaseModel):
    allow: bool
    max_qty: float
    risk_scale: float | None = Field(default=1.0, ge=0.0, le=1.0)
    cooldown_ms: int = 0
    reason: str = "ok"
    hard_gate: bool = False
    quotas: dict[str, Any] | None = None
    observability: dict[str, Any]
