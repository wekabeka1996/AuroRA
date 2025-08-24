from __future__ import annotations

from core.scalper.features import tfi_from_binance_trades


def test_binance_tfi_semantics_basic():
    trades = [
        {"price": 100, "size": 1.0, "isBuyerMaker": False},  # BUY aggressor
        {"price": 100, "size": 1.0, "isBuyerMaker": True},   # SELL aggressor
        {"price": 101, "size": 3.0, "isBuyerMaker": False},  # BUY
    ]
    dbg = tfi_from_binance_trades(trades)
    assert dbg.v_mkt_buy == 4.0
    assert dbg.v_mkt_sell == 1.0
    assert 0.0 < dbg.tfi <= 1.0


def test_binance_tfi_zero_safe():
    trades = []
    dbg = tfi_from_binance_trades(trades)
    assert dbg.v_mkt_buy == 0.0
    assert dbg.v_mkt_sell == 0.0
    assert dbg.tfi == 0.0
