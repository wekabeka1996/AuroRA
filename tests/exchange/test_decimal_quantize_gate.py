from __future__ import annotations

from decimal import Decimal

from core.execution.exchange.common import OrderRequest, OrderType, Side
from core.execution.exchange.gate import GateExchange


class DummyHttp:
    def __init__(self):
        self.last = None

    def request(self, method: str, url: str, *, params=None, headers=None, json=None):
        self.last = (method, url, params, headers, json)
        # Simulate minimal Gate responses
        if url.endswith("/spot/orders") and method == "POST":
            return {
                "id": "1",
                "text": "x",
                "status": "open",
                "filled_total": "0",
                "fill_price": "0",
            }
        return {}


def test_gate_decimal_quantize_and_wire_format():
    http = DummyHttp()
    ex = GateExchange(api_key="k", api_secret="s", http=http)

    # Defaults: tick=0.01, step=0.001, minNotional=5.0 per adapter stub meta
    req = OrderRequest(
        symbol="BTC_USDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("0.00149"),
        price=Decimal("30000.009"),
    )

    res = ex.place_order(req)
    method, url, params, headers, body = http.last
    assert method == "POST"
    assert body["amount"] == "0.001"
    assert body["price"] == "30000.00"
    assert "E" not in body["amount"] and "E" not in body["price"]


def test_gate_min_notional_enforced():
    http = DummyHttp()
    ex = GateExchange(api_key="k", api_secret="s", http=http)

    from core.execution.exchange.common import ValidationError

    req = OrderRequest(
        symbol="BTC_USDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=Decimal("0.0001"),
        price=Decimal("30.00"),
    )

    try:
        ex.place_order(req)
    except ValidationError as e:
        assert "MIN_NOTIONAL" in str(e)
    else:
        assert False, "Expected ValidationError for MIN_NOTIONAL"
