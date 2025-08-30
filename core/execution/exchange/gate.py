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
from typing import Mapping, Optional
from urllib.parse import urlencode, urlsplit

from core.execution.exchange.common import (
    AbstractExchange,
    HttpClient,
    OrderRequest,
    OrderResult,
    OrderType,
    SymbolInfo,
    Fill,
    ValidationError,
    make_idempotency_key,
)


@dataclass
class _Creds:
    key: str
    secret: str


class GateExchange(AbstractExchange):
    name = "gate"

    def __init__(self, *, api_key: str, api_secret: str, http: Optional[HttpClient] = None, base_url: str = "https://api.gateio.ws/api/v4") -> None:
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

    def _headers(self, method: str, path: str, query: Mapping[str, object] | None, body_json: str | None, ts: int) -> Mapping[str, str]:
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
        # Gate uses formats like BTC_USDT; normalize by replacing '-' with '_' and uppercasing
        sym = self.normalize_symbol(symbol).replace("_", "").upper()
        # Without HTTP client, return conservative defaults for validation
        if self._http is None:
            return SymbolInfo(symbol=sym, base=sym[:-4], quote=sym[-4:], tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5.0)
        # Gate does not provide a single unified "exchangeInfo"; for production,
        # query `/spot/currency_pairs` and parse `min_quote_amount`, `amount_precision`, `precision`
        # Here, keep it minimal to remain dependency-free.
        return SymbolInfo(symbol=sym, base=sym[:-4], quote=sym[-4:], tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5.0)

    def normalize_symbol(self, symbol: str) -> str:
        # Gate uses BTC_USDT format, so normalize by replacing separators and uppercasing
        return symbol.replace("-", "").replace("/", "").replace("_", "").upper()

    # ------------- orders -------------

    def _signed_request(self, method: str, path: str, *, query: Mapping[str, object] | None = None, body: Mapping[str, object] | None = None) -> Mapping[str, object]:
        if self._http is None:
            raise RuntimeError("No HttpClient provided for GateExchange")
        ts = int(self.server_time_ns_hint() // 1_000_000_000)  # seconds
        body_json = json.dumps(body or {}, separators=(",", ":")) if body is not None else ""
        headers = self._headers(method, path, query, body_json, ts)
        url = self._ep(path)
        return self._http.request(method, url, params=query, headers=headers, json=(body if body is not None else None))

    def place_order(self, req: OrderRequest) -> OrderResult:
        info = self.get_symbol_info(req.symbol)
        clean = self.validate_order(req, info)
        coid = clean.client_order_id or make_idempotency_key("oid", {
            "s": clean.symbol,
            "sd": clean.side.value,
            "t": clean.type.value,
            "q": clean.quantity,
            "p": clean.price if clean.price is not None else "",
        })
        # Gate expects symbol as BASE_QUOTE with underscore
        pair = f"{info.base}_{info.quote}"
        body = {
            "currency_pair": pair,
            "side": "buy" if clean.side.value == "BUY" else "sell",
            "type": "limit" if clean.type == OrderType.LIMIT else "market",
            "amount": f"{clean.quantity}",
            "text": coid,  # idempotency client id
        }
        if clean.type == OrderType.LIMIT:
            body["price"] = f"{clean.price}"
        res = self._signed_request("POST", self._order_path(), body=body)
        fills: list[Fill] = []

        # Safe type conversion for response values
        filled_total_val = res.get("filled_total", 0.0)
        fill_price_val = res.get("fill_price", 0.0)
        try:
            filled_total = float(str(filled_total_val)) if filled_total_val is not None else 0.0
        except (ValueError, TypeError):
            filled_total = 0.0
        try:
            fill_price = float(str(fill_price_val)) if fill_price_val is not None else 0.0
        except (ValueError, TypeError):
            fill_price = 0.0

        cumm_quote_cost = fill_price * filled_total if fill_price else 0.0

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

    def cancel_order(self, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> Mapping[str, object]:
        pair = self.normalize_symbol(symbol)
        path = f"{self._order_path()}/{order_id}" if order_id else self._order_path()
        # Gate supports cancel by `text` (client id) via query param
        query = {"currency_pair": pair}
        if client_order_id:
            query["text"] = client_order_id
        return self._signed_request("DELETE", path, query=query)

    def get_order(self, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> Mapping[str, object]:
        pair = self.normalize_symbol(symbol)
        path = f"{self._order_path()}/{order_id}" if order_id else self._order_path()
        query = {"currency_pair": pair}
        if client_order_id:
            query["text"] = client_order_id
        return self._signed_request("GET", path, query=query)


__all__ = ["GateExchange"]
