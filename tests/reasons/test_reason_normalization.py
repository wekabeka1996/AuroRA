from __future__ import annotations

import pytest

from exch.errors import normalize_reason_struct, aurora_guard_reason


@pytest.mark.parametrize(
    "code,msg,expected",
    [
        ("-1013", "price filter", {"reason_code": "EXCHANGE_FILTER_PRICE", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}),
        ("-1021", "ts", {"reason_code": "EXCHANGE_TIMESTAMP", "reason_class": "EXCHANGE", "severity": "WARN", "action": "RETRY_SOFT"}),
        ("-2010", "bal", {"reason_code": "EXCHANGE_INSUFFICIENT_BALANCE", "reason_class": "EXCHANGE", "severity": "ERROR", "action": "ABORT"}),
        ("-2019", "margin", {"reason_code": "EXCHANGE_MARGIN_INSUFFICIENT", "reason_class": "EXCHANGE", "severity": "ERROR", "action": "ABORT"}),
        ("-4164", "notional", {"reason_code": "EXCHANGE_NOTIONAL_MIN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}),
        ("-9999", "unknown", {"reason_code": "EXCHANGE_UNKNOWN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}),
        (None, "none", {"reason_code": "EXCHANGE_UNKNOWN", "reason_class": "EXCHANGE", "severity": "WARN", "action": "ABORT"}),
    ],
)
def test_exchange_normalization(code, msg, expected):
    got = normalize_reason_struct(code, msg)
    for k, v in expected.items():
        assert got.get(k) == v


@pytest.mark.parametrize(
    "aur_code",
    [
        "SPREAD_GUARD",
        "VOL_GUARD",
        "LATENCY_GUARD",
        "DD_GUARD",
        "CVAR_GUARD",
        "POSITION_CAP_GUARD",
        "TIME_GUARD",
    ],
)
def test_aurora_guard_helper(aur_code):
    n = aurora_guard_reason(aur_code)
    assert n["reason_code"] == aur_code
    assert n["reason_class"] == "AURORA"
    assert n["severity"] == "WARN"
    assert n["action"] == "ABORT"
