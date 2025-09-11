from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Final

# Event types/codes
POLICY_DECISION: Final = "POLICY.DECISION"
POLICY_TRAP_GUARD: Final = "POLICY.TRAP_GUARD"
POLICY_TRAP_BLOCK: Final = "POLICY.TRAP_BLOCK"

RISK_DENY: Final = "RISK.DENY"

AURORA_ESCALATION: Final = "AURORA.ESCALATION"
AURORA_RISK_WARN: Final = "AURORA.RISK_WARN"
AURORA_SLIPPAGE_GUARD: Final = "AURORA.SLIPPAGE_GUARD"
AURORA_EXPECTED_RETURN_LOW: Final = "AURORA.EXPECTED_RETURN_LOW"
AURORA_EXPECTED_RETURN_ACCEPT: Final = "AURORA.EXPECTED_RETURN_ACCEPT"
AURORA_COOL_OFF: Final = "AURORA.COOL_OFF"
AURORA_HALT: Final = "AURORA.HALT"
AURORA_RESUME: Final = "AURORA.RESUME"
OPS_RESET: Final = "OPS.RESET"
AURORA_ARM_STATE: Final = "AURORA.ARM_STATE"
RISK_UPDATE: Final = "RISK.UPDATE"
OPS_TOKEN_ROTATE: Final = "OPS.TOKEN_ROTATE"

# Idempotency events
IDEM_CHECK: Final = "IDEM.CHECK"
IDEM_STORE: Final = "IDEM.STORE"
IDEM_HIT: Final = "IDEM.HIT"
IDEM_UPDATE: Final = "IDEM.UPDATE"
IDEM_CONFLICT: Final = "IDEM.CONFLICT"
IDEM_DUP: Final = "IDEM.DUP"

# Post-trade events
POSTTRADE_LOG: Final = "POSTTRADE.LOG"

# Data quality events
DQ_EVENT_STALE_BOOK: Final = "DQ_EVENT.STALE_BOOK"
DQ_EVENT_CROSSED_BOOK: Final = "DQ_EVENT.CROSSED_BOOK"
DQ_EVENT_ABNORMAL_SPREAD: Final = "DQ_EVENT.ABNORMAL_SPREAD"
DQ_EVENT_CYCLIC_SEQUENCE: Final = "DQ_EVENT.CYCLIC_SEQUENCE"

HEALTH_LATENCY_HIGH: Final = "HEALTH.LATENCY_HIGH"
HEALTH_LATENCY_P95_HIGH: Final = "HEALTH.LATENCY_P95_HIGH"

# SPRT/Governance events
SPRT_DECISION_H0: Final = "SPRT.DECISION_H0"
SPRT_DECISION_H1: Final = "SPRT.DECISION_H1"
SPRT_CONTINUE: Final = "SPRT.CONTINUE"
SPRT_ERROR: Final = "SPRT.ERROR"

# Execution events (Step 3)
EXEC_DECISION: Final = "EXEC.DECISION"
ORDER_ACK: Final = "ORDER.ACK"
ORDER_CXL: Final = "ORDER.CXL"
ORDER_REPLACE: Final = "ORDER.REPLACE"
FILL_EVENT: Final = "FILL.EVENT"

# Reward events (Step 3)
REWARD_UPDATE: Final = "REWARD.UPDATE"
POSITION_CLOSED: Final = "POSITION.CLOSED"

# TCA events (Step 3)
TCA_ANALYSIS: Final = "TCA.ANALYSIS"


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


def validate_event(event_data: Dict[str, Any]) -> bool:
    """
    Validate event data against schema.json
    Returns True if valid, False otherwise.
    """
    try:
        schema_path = Path(__file__).parent / "schema.json"
        if not schema_path.exists():
            # No schema file - skip validation
            return True

        with open(schema_path, "r", encoding="utf-8") as f:
            schema = json.load(f)

        # Basic validation - check required fields exist
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in event_data:
                return False

        # Check event type is known if specified in schema
        event_type = event_data.get("type")
        if event_type and "properties" in schema:
            type_prop = schema["properties"].get("type", {})
            if "enum" in type_prop and event_type not in type_prop["enum"]:
                return False

        return True
    except Exception:
        # Validation failed - assume invalid
        return False


def get_all_event_codes() -> list[str]:
    """Get all defined event code constants"""
    return [
        POLICY_DECISION,
        POLICY_TRAP_GUARD,
        POLICY_TRAP_BLOCK,
        RISK_DENY,
        AURORA_ESCALATION,
        AURORA_RISK_WARN,
        AURORA_SLIPPAGE_GUARD,
        AURORA_EXPECTED_RETURN_LOW,
        AURORA_EXPECTED_RETURN_ACCEPT,
        AURORA_COOL_OFF,
        AURORA_HALT,
        AURORA_RESUME,
        OPS_RESET,
        AURORA_ARM_STATE,
        RISK_UPDATE,
        OPS_TOKEN_ROTATE,
        POSTTRADE_LOG,
        DQ_EVENT_STALE_BOOK,
        DQ_EVENT_CROSSED_BOOK,
        DQ_EVENT_ABNORMAL_SPREAD,
        DQ_EVENT_CYCLIC_SEQUENCE,
        HEALTH_LATENCY_HIGH,
        HEALTH_LATENCY_P95_HIGH,
        SPRT_DECISION_H0,
        SPRT_DECISION_H1,
        SPRT_CONTINUE,
        SPRT_ERROR,
        # Step 3 events
        EXEC_DECISION,
        ORDER_ACK,
        ORDER_CXL,
        ORDER_REPLACE,
        FILL_EVENT,
        REWARD_UPDATE,
        POSITION_CLOSED,
        TCA_ANALYSIS,
        # Idempotency events
        IDEM_CHECK,
        IDEM_STORE,
        IDEM_HIT,
        IDEM_UPDATE,
        IDEM_CONFLICT,
        IDEM_DUP,
    ]
