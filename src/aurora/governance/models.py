from __future__ import annotations
from dataclasses import dataclass


@dataclass
class PerfSnapshot:
    trades: int
    window_ms: int
    sr: float
    pvalue_glr: float
    sprt_pass: bool
    edge_mean_bps: float
    latency_p95_ms: int
    xai_missing_rate: float
    cvar_breach: bool
    sla_breach_rate: float


@dataclass
class GovernanceDecision:
    mode: str  # shadow|canary|live
    reason: str
    alpha_spent: float
    allow: bool
