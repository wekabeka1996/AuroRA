from __future__ import annotations

from typing import Literal, Optional, Dict, Any
from pydantic import BaseModel, Field


class DecisionFinal(BaseModel):
    ts_iso: str
    decision_id: str
    symbol: str
    side: Literal['BUY', 'SELL']
    score: float
    signals: Dict[str, Any] = Field(default_factory=dict)
    intent: Dict[str, Any] = Field(default_factory=dict)


class OrderBase(BaseModel):
    ts_iso: str
    decision_id: str
    order_id: str
    symbol: str
    side: str
    qty: float
    # Correlation IDs
    client_order_id: Optional[str] = None
    exchange_order_id: Optional[str] = None


class OrderSuccess(OrderBase):
    avg_price: float
    fees: float
    filled_pct: float
    exchange_ts: Optional[str] = None


class OrderFailed(OrderBase):
    error_code: str
    error_msg: str
    attempts: int
    final_status: str


class OrderDenied(OrderBase):
    gate_code: str
    gate_detail: Dict[str, Any] = Field(default_factory=dict)
    snapshot: Dict[str, Any] = Field(default_factory=dict)
    # Normalized reject reason (AUR-003)
    reason_normalized: str = Field(default="UNKNOWN")
