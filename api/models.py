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


class PretradeCheckRequest(BaseModel):
    ts: Optional[int] = None
    req_id: Optional[str] = None
    account: Dict[str, Any]
    order: Dict[str, Any]
    market: Dict[str, Any]
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
