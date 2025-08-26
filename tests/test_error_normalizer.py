from __future__ import annotations

from exch.errors import normalize_reason, BINANCE_FUTURES_ERROR_MAP


def test_known_codes_normalized():
    for code, expected in BINANCE_FUTURES_ERROR_MAP.items():
        assert normalize_reason(code, "") == expected
        assert normalize_reason(int(code), "") == expected


def test_unknown_code_fallback():
    assert normalize_reason("-9999", "something") == "UNKNOWN"
    assert normalize_reason(None, None) == "UNKNOWN"
