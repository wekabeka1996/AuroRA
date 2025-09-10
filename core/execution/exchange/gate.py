from __future__ import annotations

"""
Exchange Adapter — Gate.io (Spot skeleton)
=========================================

A minimal, dependency-free Gate.io adapter sharing the common exchange
interfaces. Focuses on deterministic order validation, idempotent client IDs,
and HMAC-SHA512 request signing according to Gate's scheme.

Notes
-----
- Real network calls require providing an `HttpClient` implementation.
- The signing string is composed as: `timestamp\nmethod\n/path\nquery\nbody` and
  the signature is `hex(hmac_sha512(secret, prehash))`. Headers must include
  `KEY`, `SIGN`, and `Content-Type: application/json`.
"""

import json
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Mapping, Optional
from urllib.parse import urlencode, urlsplit

from common.decimal_utils import q_dec, quantize_step, str_decimal, str_decimal_step
from common.symbol_codec import GateCodec
from core.execution.exchange.common import (
    AbstractExchange,
    Fill,
    HttpClient,
    OrderRequest,
    OrderResult,
    OrderType,
    SymbolInfo,
    ValidationError,
    make_idempotency_key,
)


@dataclass
class _Creds:
    key: str
    secret: str


class GateExchange(AbstractExchange):
    name = "gate"
    CODEC = GateCodec()

    def __init__(
        self,
        *,
        api_key: str,
        api_secret: str,
        http: Optional[HttpClient] = None,
        base_url: str = "https://api.gateio.ws/api/v4",
    ) -> None:
        super().__init__(http=http)
        self._creds = _Creds(api_key, api_secret)
        self._base = base_url.rstrip("/")

    # ------------- endpoints -------------

    def _ep(self, path: str) -> str:
        return f"{self._base}{path}"

    def _order_path(self) -> str:
        return "/spot/orders"

    def _ticker_path(self, symbol: str) -> str:
        return "/spot/tickers"

    # ------------- signing -------------

    def _headers(
        self,
        method: str,
        path: str,
        query: Mapping[str, object] | None,
        body_json: str | None,
        ts: int,
    ) -> Mapping[str, str]:
        # Gate prehash: timestamp + '\n' + method + '\n' + path + '\n' + query + '\n' + body
        q = urlencode(query or {}, doseq=True)
        prehash = f"{ts}\n{method}\n{path}\n{q}\n{body_json or ''}"
        sig = self.hmac_sha512(self._creds.secret, prehash)
        return {
            "KEY": self._creds.key,
            "SIGN": sig,
            "Content-Type": "application/json",
        }

    # ------------- meta -------------

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        base, quote = self.CODEC.decode(symbol)
        pair = self.CODEC.encode(base, quote)
        # Without HTTP client, return conservative defaults for validation
        if self._http is None:
            return SymbolInfo(
                symbol=pair.replace("_", ""),
                base=base,
                quote=quote,
                tick_size=0.01,
                step_size=0.001,
                min_qty=0.001,
                min_notional=5.0,
            )
        # Gate does not provide a single unified "exchangeInfo"; for production,
        # query `/spot/currency_pairs` and parse `min_quote_amount`, `amount_precision`, `precision`
        # Here, keep it minimal to remain dependency-free.
        return SymbolInfo(
            symbol=pair.replace("_", ""),
            base=base,
            quote=quote,
            tick_size=0.01,
            step_size=0.001,
            min_qty=0.001,
            min_notional=5.0,
        )

    def normalize_symbol(self, symbol: str) -> str:
        # Use codec for normalization
        return self.CODEC.encode(*self.CODEC.decode(symbol)).replace("_", "")

    # ------------- orders -------------

    def _signed_request(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, object] | None = None,
        body: Mapping[str, object] | None = None,
    ) -> Mapping[str, object]:
        if self._http is None:
            raise RuntimeError("No HttpClient provided for GateExchange")
        ts = int(self.server_time_ns_hint() // 1_000_000_000)  # seconds
        body_json = (
            json.dumps(body or {}, separators=(",", ":")) if body is not None else ""
        )
        headers = self._headers(method, path, query, body_json, ts)
        url = self._ep(path)
        return self._http.request(
            method,
            url,
            params=query,
            headers=headers,
            json=(body if body is not None else None),
        )

    def place_order(self, req: OrderRequest) -> OrderResult:
        info = self.get_symbol_info(req.symbol)
        # Convert inbound to Decimal
        qty_in = q_dec(req.quantity)
        price_in: Optional[Decimal] = (
            q_dec(req.price) if req.price is not None else None
        )
        # Filters (using defaults/stub for now)
        tick = q_dec(info.tick_size)
        step = q_dec(info.step_size)
        min_notional = q_dec(info.min_notional)
        min_qty = q_dec(info.min_qty)
        # Quantize
        qty_q = quantize_step(qty_in, step, ROUND_DOWN)
        price_q: Optional[Decimal] = None
        if req.type == OrderType.LIMIT:
            if price_in is None:
                raise ValidationError("LIMIT order requires price")
            price_q = quantize_step(price_in, tick, ROUND_DOWN)
        # Checks: follow MIN_NOTIONAL first to align with tests
        if req.type == OrderType.LIMIT:
            notional = (price_q or Decimal("0")) * qty_q
            if notional < min_notional:
                raise ValidationError("MIN_NOTIONAL")
        if qty_q < min_qty:
            raise ValidationError(f"qty {qty_q} < min_qty {min_qty}")
        coid = req.client_order_id or make_idempotency_key(
            "oid",
            {
                "s": info.symbol,
                "sd": req.side.value,
                "t": req.type.value,
                "q": str_decimal(qty_q),
                "p": str_decimal(price_q) if price_q is not None else "",
            },
        )
        # Gate expects symbol as BASE_QUOTE with underscore
        pair = f"{info.base}_{info.quote}"
        body = {
            "currency_pair": pair,
            "side": "buy" if req.side.value == "BUY" else "sell",
            "type": "limit" if req.type == OrderType.LIMIT else "market",
            "amount": str_decimal_step(qty_q, step),
            "text": coid,  # idempotency client id
        }
        if req.type == OrderType.LIMIT and price_q is not None:
            body["price"] = str_decimal_step(price_q, tick)
        res = self._signed_request("POST", self._order_path(), body=body)
        fills: list[Fill] = []

        # Safe conversion for response values using Decimal
        filled_total_val = res.get("filled_total", "0")
        fill_price_val = res.get("fill_price", "0")
        filled_total = (
            q_dec(filled_total_val) if filled_total_val is not None else Decimal("0")
        )
        fill_price = (
            q_dec(fill_price_val) if fill_price_val is not None else Decimal("0")
        )

        cumm_quote_cost = fill_price * filled_total if fill_price else Decimal("0")

        return OrderResult(
            order_id=str(res.get("id", "")),
            client_order_id=str(res.get("text", coid)),
            status=str(res.get("status", "open")),
            executed_qty=filled_total,
            cumm_quote_cost=cumm_quote_cost,
            fills=fills,
            ts_ns=int(self.server_time_ns_hint()),
            raw=res,
        )

    def cancel_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:
        pair = self.normalize_symbol(symbol)
        path = f"{self._order_path()}/{order_id}" if order_id else self._order_path()
        # Gate supports cancel by `text` (client id) via query param
        query = {"currency_pair": pair}
        if client_order_id:
            query["text"] = client_order_id
        return self._signed_request("DELETE", path, query=query)

    def get_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:
        pair = self.normalize_symbol(symbol)
        path = f"{self._order_path()}/{order_id}" if order_id else self._order_path()
        query = {"currency_pair": pair}
        if client_order_id:
            query["text"] = client_order_id
        return self._signed_request("GET", path, query=query)


__all__ = ["GateExchange"]
