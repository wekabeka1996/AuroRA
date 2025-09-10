from __future__ import annotations

"""
Exchange Adapter — Binance (Spot/Futures skeleton)
==================================================

A dependency-free Binance adapter built on the common exchange primitives.
It focuses on:
- Deterministic validation/quantization of orders
- Canonical request signing (HMAC-SHA256)
- Idempotent client order IDs
- Pluggable HTTP client (Protocol) to enable real I/O in production

Notes
-----
- Endpoints and signing follow Binance conventions but this module avoids making
  actual network calls unless an HttpClient is provided at construction.
- Only a minimal subset (place/cancel/get, exchangeInfo, server time) is modeled
  as a reliable skeleton. Extend as needed.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast
from urllib.parse import urlencode

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


class BinanceExchange(AbstractExchange):
    name = "binance"

    def __init__(self, *, api_key: str, api_secret: str, http: HttpClient | None = None, futures: bool = False, base_url: str | None = None) -> None:
        super().__init__(http=http)
        self._creds = _Creds(api_key, api_secret)
        self._is_futures = bool(futures)
        if base_url is None:
            base_url = "https://fapi.binance.com" if futures else "https://api.binance.com"
        self._base = base_url.rstrip("/")

    # ------------- endpoints -------------

    def _ep(self, path: str) -> str:
        return f"{self._base}{path}"

    def _time_path(self) -> str:
        return "/fapi/v1/time" if self._is_futures else "/api/v3/time"

    def _exchange_info_path(self) -> str:
        return "/fapi/v1/exchangeInfo" if self._is_futures else "/api/v3/exchangeInfo"

    def _order_path(self) -> str:
        return "/fapi/v1/order" if self._is_futures else "/api/v3/order"

    # ------------- auth/sign -------------

    def _sign(self, params_qs: str) -> str:
        return self.hmac_sha256(self._creds.secret, params_qs)

    def _auth_headers(self) -> Mapping[str, str]:
        return {"X-MBX-APIKEY": self._creds.key}

    # ------------- API -------------

    def get_server_time_ms(self) -> int:
        if self._http is None:
            return int(self.server_time_ns_hint() // 1_000_000)
        out = cast(dict[str, Any], self._http.request("GET", self._ep(self._time_path())))
        return int(out.get("serverTime", 0))

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        sym = self.normalize_symbol(symbol)
        if self._http is None:
            # Conservative defaults for offline validation; override in production
            return SymbolInfo(symbol=sym, base=sym[:-4], quote=sym[-4:], tick_size=0.01, step_size=0.001, min_qty=0.001, min_notional=5.0)
        data = cast(dict[str, Any], self._http.request("GET", self._ep(self._exchange_info_path()), params={"symbol": sym}))
        symbols = cast(list, data.get("symbols")) or cast(list, data.get("symbols", []))
        if not symbols:
            # Some endpoints return single-symbol object under 'symbols' or 'symbol'
            symbol_data = cast(dict[str, Any], data.get("symbol")) if data.get("symbol") else None
            symbols = [symbol_data] if symbol_data else []
        if not symbols:
            raise ValidationError(f"symbol {sym} not found")
        s = symbols[0]
        base = str(s.get("baseAsset", "")) if isinstance(s, dict) else ""
        quote = str(s.get("quoteAsset", "")) if isinstance(s, dict) else ""
        tick = 0.0
        step = 0.0
        min_qty = 0.0
        min_notional = 0.0
        if isinstance(s, dict):
            for f in s.get("filters", []):
                if isinstance(f, dict):
                    t = f.get("filterType")
                    if t == "PRICE_FILTER":
                        tick = float(f.get("tickSize", 0.0))
                    elif t == "LOT_SIZE":
                        step = float(f.get("stepSize", 0.0))
                        min_qty = float(f.get("minQty", 0.0))
                    elif t == "MIN_NOTIONAL":
                        min_notional = float(f.get("minNotional", 0.0))
        return SymbolInfo(symbol=sym, base=base, quote=quote, tick_size=tick or 0.0, step_size=step or 0.0, min_qty=min_qty or 0.0, min_notional=min_notional or 0.0)

    # ------------- order ops -------------

    def _signed_request(self, method: str, path: str, params: Mapping[str, object]) -> Mapping[str, object]:
        if self._http is None:
            raise RuntimeError("No HttpClient provided for BinanceExchange")
        qs = urlencode(params, doseq=True)
        sig = self._sign(qs)
        url = self._ep(path) + "?" + qs + "&signature=" + sig
        return self._http.request(method, url, headers=self._auth_headers())

    def place_order(self, req: OrderRequest) -> OrderResult:
        # fetch symbol info for precise rounding
        info = self.get_symbol_info(req.symbol)
        clean = self.validate_order(req, info)
        # idempotency key
        coid = clean.client_order_id or make_idempotency_key("oid", {
            "s": clean.symbol,
            "sd": clean.side.value,
            "t": clean.type.value,
            "q": clean.quantity,
            "p": clean.price if clean.price is not None else "",
        })
        ts = self.get_server_time_ms()
        params = {
            "symbol": self.normalize_symbol(clean.symbol),
            "side": clean.side.value,
            "type": clean.type.value,
            "quantity": f"{clean.quantity}",
            "newClientOrderId": coid,
            "timestamp": ts,
            "recvWindow": 5000,
        }
        if clean.type == OrderType.LIMIT:
            params.update({"price": f"{clean.price}", "timeInForce": clean.tif.value})
        res = cast(dict[str, Any], self._signed_request("POST", self._order_path(), params))
        # map result (fields follow Binance JSON structure; keep raw)
        fills = []
        fills_data = res.get("fills", [])
        if isinstance(fills_data, list):
            for f in fills_data:
                if isinstance(f, dict):
                    fills.append(Fill(
                        price=float(f.get("price", 0.0)),
                        qty=float(f.get("qty", 0.0)),
                        fee=float(f.get("commission", 0.0)),
                        fee_asset=str(f.get("commissionAsset", "")),
                        ts_ns=int(self.server_time_ns_hint()),
                    ))
        executed_qty_val = res.get("executedQty", 0.0)
        cumm_quote_cost_val = res.get("cummulativeQuoteQty", 0.0)
        try:
            executed_qty = float(str(executed_qty_val)) if executed_qty_val is not None else 0.0
        except (ValueError, TypeError):
            executed_qty = 0.0
        try:
            cumm_quote_cost = float(str(cumm_quote_cost_val)) if cumm_quote_cost_val is not None else 0.0
        except (ValueError, TypeError):
            cumm_quote_cost = 0.0
        return OrderResult(
            order_id=str(res.get("orderId", "")),
            client_order_id=str(res.get("clientOrderId", coid)),
            status=str(res.get("status", "NEW")),
            executed_qty=executed_qty,
            cumm_quote_cost=cumm_quote_cost,
            fills=fills,
            ts_ns=int(self.server_time_ns_hint()),
            raw=res,
        )

    def cancel_order(self, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> Mapping[str, object]:
        ts = self.get_server_time_ms()
        params = {
            "symbol": self.normalize_symbol(symbol),
            "timestamp": ts,
            "recvWindow": 5000,
        }
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        return cast(dict[str, Any], self._signed_request("DELETE", self._order_path(), params))

    def get_order(self, symbol: str, order_id: str | None = None, client_order_id: str | None = None) -> Mapping[str, object]:
        ts = self.get_server_time_ms()
        params = {
            "symbol": self.normalize_symbol(symbol),
            "timestamp": ts,
            "recvWindow": 5000,
        }
        if order_id:
            params["orderId"] = order_id
        if client_order_id:
            params["origClientOrderId"] = client_order_id
        return cast(dict[str, Any], self._signed_request("GET", self._order_path(), params))


__all__ = ["BinanceExchange"]
