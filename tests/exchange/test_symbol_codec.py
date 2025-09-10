from __future__ import annotations

from common.symbol_codec import BinanceCodec, GateCodec


def test_binance_codec_roundtrip_cases():
    b = BinanceCodec()
    cases = [
        ("BTC", "USDT"),
        ("ETH", "USDT"),
        ("SOL", "USDT"),
        ("ARB", "USDT"),
        ("XRP", "USDT"),
    ]
    for base, quote in cases:
        sym = b.encode(base.lower(), quote.lower())  # lower to test uppercasing
        db, dq = b.decode(sym.lower())  # lower to test case-insensitivity
        assert (db, dq) == (base, quote)


def test_gate_codec_roundtrip_cases():
    g = GateCodec()
    cases = [
        ("BTC", "USDT"),
        ("ETH", "USDT"),
        ("SOL", "USDT"),
        ("ARB", "USDT"),
        ("XRP", "USDT"),
    ]
    for base, quote in cases:
        sym = g.encode(base, quote)
        db, dq = g.decode(sym)
        assert (db, dq) == (base, quote)

    # Gate decoding should handle binance-like too
    db, dq = g.decode("btcusdt")
    assert (db, dq) == ("BTC", "USDT")
