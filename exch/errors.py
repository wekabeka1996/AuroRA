from __future__ import annotations

from typing import Any

# Normalized structure
# reason_class: AURORA | EXCHANGE
# severity: INFO | WARN | ERROR
# action: RETRY_SOFT | RETRY_HARD | ABORT

Normalized = dict[str, Any]

# Binance Futures common error codes mapping to normalized reasons
BINANCE_FUTURES_ERROR_MAP: dict[str, Normalized] = {
    "-1013": {"reason_code": "EXCHANGE_FILTER_PRICE", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"},
    "-1021": {"reason_code": "EXCHANGE_TIMESTAMP", "reason_class": "EXCHANGE", "severity": "WARN", "action": "RETRY_SOFT"},
    "-2010": {"reason_code": "EXCHANGE_INSUFFICIENT_BALANCE", "reason_class": "EXCHANGE", "severity": "ERROR", "action": "ABORT"},
    "-2019": {"reason_code": "EXCHANGE_MARGIN_INSUFFICIENT", "reason_class": "EXCHANGE", "severity": "ERROR", "action": "ABORT"},
    "-4164": {"reason_code": "EXCHANGE_NOTIONAL_MIN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"},
}


def normalize_reason_struct(raw_code: str | int | None, raw_msg: str | None) -> Normalized:
    """Return normalized structure for an exchange error.
    Unknown codes map to EXCHANGE_UNKNOWN with WARN severity and ABORT action.
    """
    if raw_code is None:
        return {"reason_code": "EXCHANGE_UNKNOWN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}
    code = str(raw_code).strip()
    if code in BINANCE_FUTURES_ERROR_MAP:
        return dict(BINANCE_FUTURES_ERROR_MAP[code])
    return {"reason_code": "EXCHANGE_UNKNOWN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}


def normalize_reason(raw_code: str | int | None, raw_msg: str | None):
    """Back-compat helper used in tests.

    Behavior per tests:
    - For known Binance futures error codes, return the full normalized dict (not just the code).
    - For unknown codes or None, return string "UNKNOWN".
    """
    if raw_code is None:
        return "UNKNOWN"
    code = str(raw_code).strip()
    if code in BINANCE_FUTURES_ERROR_MAP:
        return dict(BINANCE_FUTURES_ERROR_MAP[code])
    return "UNKNOWN"


def aurora_guard_reason(code: str, detail: str | None = None) -> Normalized:
    """Helper for AURORA guard denials.
    code examples: SPREAD_GUARD, VOL_GUARD, LATENCY_GUARD, DD_GUARD, CVAR_GUARD, POSITION_CAP_GUARD, TIME_GUARD
    """
    return {
        "reason_code": code,
        "reason_class": "AURORA",
        "severity": "WARN",
        "action": "ABORT",
        "reason_detail": detail,
    }
