from __future__ import annotations

from typing import Final

# Event types/codes
POLICY_DECISION: Final = "POLICY.DECISION"
POLICY_TRAP_GUARD: Final = "POLICY.TRAP_GUARD"
POLICY_TRAP_BLOCK: Final = "POLICY.TRAP_BLOCK"

RISK_DENY: Final = "RISK.DENY"

AURORA_ESCALATION: Final = "AURORA.ESCALATION"
AURORA_RISK_WARN: Final = "AURORA.RISK_WARN"
AURORA_SLIPPAGE_GUARD: Final = "AURORA.SLIPPAGE_GUARD"
AURORA_EXPECTED_RETURN_LOW: Final = "AURORA.EXPECTED_RETURN_LOW"
AURORA_COOL_OFF: Final = "AURORA.COOL_OFF"
OPS_RESET: Final = "OPS.RESET"
AURORA_ARM_STATE: Final = "AURORA.ARM_STATE"
RISK_UPDATE: Final = "RISK.UPDATE"
OPS_TOKEN_ROTATE: Final = "OPS.TOKEN_ROTATE"

HEALTH_LATENCY_HIGH: Final = "HEALTH.LATENCY_HIGH"
HEALTH_LATENCY_P95_HIGH: Final = "HEALTH.LATENCY_P95_HIGH"


def is_latency(ev_type_or_code: str) -> bool:
    s = str(ev_type_or_code or "").upper()
    return s.startswith("HEALTH.LATENCY_") or s in {AURORA_ESCALATION}


def is_risk(ev_type_or_code: str) -> bool:
    return str(ev_type_or_code or "").upper().startswith("RISK.")


def normalize_reason(reason: str) -> str:
    r = str(reason or "")
    if r.startswith("trap_guard"):
        return "trap_guard"
    if r.startswith("latency_"):
        return r
    if r.startswith("slippage_guard"):
        return "slippage_guard"
    if r.startswith("expected_return") or r == "expected_return_gate":
        return "expected_return_gate"
    return r
