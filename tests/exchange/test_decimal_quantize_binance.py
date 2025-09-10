from __future__ import annotations

from decimal import Decimal

from core.execution.exchange.binance import BinanceExchange
from core.execution.exchange.common import OrderRequest, OrderType, Side


class DummyHttp:
    def __init__(self):
        self.last = None

    def request(self, method: str, url: str, *, params=None, headers=None, json=None):
        self.last = (method, url, params, headers, json)
        # Simulate minimal Binance response
        if url.endswith("/api/v3/exchangeInfo") or url.endswith(
            "/fapi/v1/exchangeInfo"
        ):
            return {
                "symbols": [
                    {
                        "baseAsset": "BTC",
                        "quoteAsset": "USDT",
                        "filters": [
                            {"filterType": "PRICE_FILTER", "tickSize": "0.01"},
                            {
                                "filterType": "LOT_SIZE",
                                "stepSize": "0.001",
                                "minQty": "0.001",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "5"},
                        ],
                    }
                ]
            }
        if "/order" in url and method == "POST":
            return {
                "orderId": 1,
                "clientOrderId": "x",
                "status": "NEW",
                "executedQty": "0",
                "cummulativeQuoteQty": "0",
            }
        if "/order" in url and method == "GET":
            return {"status": "NEW"}
        return {}


def test_binance_decimal_quantize_and_wire_format():
    http = DummyHttp()
    ex = BinanceExchange(api_key="k", api_secret="s", http=http)

    # Prepare LIMIT order with values that require quantization
    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("0.00149"),
        price=Decimal("30000.009"),
    )

    res = ex.place_order(req)
    # Verify wire params prepared in DummyHttp
    method, url, params, headers, _ = http.last
    assert method == "POST"
    assert params["quantity"] == "0.001"  # step=0.001 rounded down
    assert params["price"] == "30000.00"  # tick=0.01 rounded down
    assert (
        "E" not in params["quantity"] and "E" not in params["price"]
    )  # no exp notation


def test_binance_min_notional_enforced():
    http = DummyHttp()
    ex = BinanceExchange(api_key="k", api_secret="s", http=http)

    # Price*Qty just below minNotional (5)
    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("0.0001"),
        price=Decimal("30.00"),
    )

    from core.execution.exchange.common import ValidationError

    try:
        ex.place_order(req)
    except ValidationError as e:
        assert "MIN_NOTIONAL" in str(e)
    else:
        assert False, "Expected ValidationError for MIN_NOTIONAL"
