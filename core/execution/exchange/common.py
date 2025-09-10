from __future__ import annotations

"""
Execution.Exchange — Common primitives
=====================================

Dependency-free primitives shared by exchange adapters (Binance/Gate/...):
- Data models (orders, fills, symbol filters)
- Validation & quantization against exchange constraints
- Idempotency key generation
- Abstract base class for concrete adapters
- Simple token-bucket rate limiter

This module **does not** perform network I/O; concrete adapters may accept an
HTTP client (protocol) or implement their own I/O.
"""

import hashlib
import hmac
import threading
import time
from dataclasses import dataclass
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, getcontext
from enum import Enum
from typing import Dict, List, Mapping, Optional, Protocol, Tuple

# Higher precision for Decimal ops
getcontext().prec = 28


# --------------------------- Errors ---------------------------


class ExchangeError(RuntimeError):
    pass


class ValidationError(ExchangeError):
    pass


class RateLimitError(ExchangeError):
    pass


# --------------------------- Models ---------------------------


class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class TimeInForce(str, Enum):
    GTC = "GTC"
    IOC = "IOC"
    FOK = "FOK"


@dataclass
class SymbolInfo:
    symbol: str
    base: str
    quote: str
    tick_size: float  # price increment
    step_size: float  # qty increment
    min_qty: float
    min_notional: float
    price_decimals: Optional[int] = None
    qty_decimals: Optional[int] = None


@dataclass
class OrderRequest:
    symbol: str
    side: Side
    type: OrderType
    quantity: float
    price: Optional[float] = None
    tif: TimeInForce = TimeInForce.GTC
    client_order_id: Optional[str] = None


@dataclass
class Fill:
    price: Decimal
    qty: Decimal
    fee: Decimal
    fee_asset: str
    ts_ns: int


@dataclass
class OrderResult:
    order_id: str
    client_order_id: str
    status: str
    executed_qty: Decimal
    cumm_quote_cost: Decimal
    fills: List[Fill]
    ts_ns: int
    raw: Mapping[str, object]


@dataclass
class Fees:
    """Exchange fee structure with maker/taker rates and rebates."""

    maker_fee_bps: float  # Maker fee in basis points (e.g., -0.1 for 0.1% rebate)
    taker_fee_bps: float  # Taker fee in basis points (e.g., 0.1 for 0.1%)

    @property
    def maker_fee_rate(self) -> float:
        """Maker fee as decimal (negative for rebates)."""
        return self.maker_fee_bps / 10000.0

    @property
    def taker_fee_rate(self) -> float:
        """Taker fee as decimal."""
        return self.taker_fee_bps / 10000.0

    @classmethod
    def from_exchange_config(cls, exchange_name: str) -> "Fees":
        """Create Fees from SSOT config for given exchange."""
        try:
            from core.config.loader import get_config

            cfg = get_config()
            base_key = f"execution.exchange.{exchange_name}"

            maker_bps = float(cfg.get(f"{base_key}.maker_fee_bps", 0.1))
            taker_bps = float(cfg.get(f"{base_key}.taker_fee_bps", 0.1))

            return cls(maker_fee_bps=maker_bps, taker_fee_bps=taker_bps)
        except Exception:
            # Conservative defaults
            return cls(maker_fee_bps=0.1, taker_fee_bps=0.1)


# --------------------------- Helpers ---------------------------


def _quantize(x: float, step: float, *, mode: str = "floor") -> float:
    """Quantize x to a multiple of `step` using Decimal for exactness.

    mode: 'floor' (ROUND_DOWN) or 'round' (ROUND_HALF_UP)
    """
    if step <= 0:
        return float(x)
    dx = Decimal(str(x))
    ds = Decimal(str(step))
    q = dx / ds
    if mode == "round":
        q = q.to_integral_value(rounding=ROUND_HALF_UP)
    else:
        q = q.to_integral_value(rounding=ROUND_DOWN)
    return float(q * ds)


def apply_symbol_filters(req: OrderRequest, info: SymbolInfo) -> OrderRequest:
    """Return a **new** OrderRequest rounded/clamped to exchange filters.

    - price rounded down to tick_size (for LIMIT)
    - quantity rounded down to step_size
    - enforce min_qty and min_notional
    """
    qty = _quantize(req.quantity, info.step_size, mode="floor")
    price = req.price
    if req.type == OrderType.LIMIT:
        if price is None:
            raise ValidationError("LIMIT order requires price")
        price = _quantize(price, info.tick_size, mode="floor")
    # notional check
    notional = (price if price is not None else 0.0) * qty
    if qty < info.min_qty:
        raise ValidationError(f"qty {qty} < min_qty {info.min_qty}")
    if req.type == OrderType.LIMIT and notional < info.min_notional:
        raise ValidationError(f"notional {notional} < min_notional {info.min_notional}")
    return OrderRequest(
        symbol=req.symbol,
        side=req.side,
        type=req.type,
        quantity=qty,
        price=price,
        tif=req.tif,
        client_order_id=req.client_order_id,
    )


def make_idempotency_key(prefix: str, payload: Mapping[str, object]) -> str:
    """Deterministic id-key from stable JSON-like mapping (order fields)."""
    # stable key ordering
    items = sorted((k, payload[k]) for k in payload)
    s = "|".join(f"{k}={v}" for k, v in items)
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()[:24]
    return f"{prefix}_{h}"


# --------------------------- Rate Limiter ---------------------------


class TokenBucket:
    """Simple token-bucket rate limiter.

    capacity: max tokens; refill_rate: tokens per second.
    call `acquire(tokens=1)` before making a request; raises RateLimitError if
    cannot acquire within timeout (non-blocking by design for trading loops).
    """

    def __init__(self, *, capacity: int, refill_rate: float) -> None:
        self.capacity = int(capacity)
        self.refill_rate = float(refill_rate)
        self._tokens = float(capacity)
        self._last = time.perf_counter()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.perf_counter()
        dt = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + dt * self.refill_rate)

    def acquire(self, tokens: float = 1.0) -> None:
        with self._lock:
            self._refill()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return
            raise RateLimitError("rate limit exceeded")


# --------------------------- HTTP Protocol ---------------------------


class HttpClient(Protocol):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, object]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json: Optional[object] = None,
    ) -> Mapping[str, object]: ...


# --------------------------- Abstract Exchange ---------------------------


class AbstractExchange:
    name: str = "abstract"

    def __init__(self, *, http: Optional[HttpClient] = None) -> None:
        self._http = http

    # ---- time ----
    @staticmethod
    def server_time_ns_hint() -> int:
        return time.time_ns()

    # ---- symbol meta ----
    def normalize_symbol(self, symbol: str) -> str:
        return symbol.replace("-", "").replace("/", "").upper()

    def get_symbol_info(
        self, symbol: str
    ) -> SymbolInfo:  # pragma: no cover (interface)
        raise NotImplementedError

    # ---- orders ----
    def place_order(self, req: OrderRequest) -> OrderResult:  # pragma: no cover
        raise NotImplementedError

    def cancel_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:  # pragma: no cover
        raise NotImplementedError

    def get_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:  # pragma: no cover
        raise NotImplementedError

    # ---- utils ----
    def validate_order(
        self, req: OrderRequest, info: Optional[SymbolInfo] = None
    ) -> OrderRequest:
        if info is None:
            info = self.get_symbol_info(req.symbol)
        clean = apply_symbol_filters(req, info)
        # Generate client_order_id if not provided
        if clean.client_order_id is None:
            clean = OrderRequest(
                symbol=clean.symbol,
                side=clean.side,
                type=clean.type,
                quantity=clean.quantity,
                price=clean.price,
                tif=clean.tif,
                client_order_id=make_idempotency_key(
                    "oid",
                    {
                        "s": clean.symbol,
                        "sd": clean.side.value,
                        "t": clean.type.value,
                        "q": clean.quantity,
                        "p": clean.price if clean.price is not None else "",
                    },
                ),
            )
        return clean

    @staticmethod
    def hmac_sha256(secret: str, msg: str) -> str:
        return hmac.new(
            secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha256
        ).hexdigest()

    @staticmethod
    def hmac_sha512(secret: str, msg: str) -> str:
        return hmac.new(
            secret.encode("utf-8"), msg.encode("utf-8"), hashlib.sha512
        ).hexdigest()


__all__ = [
    "ExchangeError",
    "ValidationError",
    "RateLimitError",
    "Side",
    "OrderType",
    "TimeInForce",
    "SymbolInfo",
    "OrderRequest",
    "Fill",
    "OrderResult",
    "Fees",
    "apply_symbol_filters",
    "make_idempotency_key",
    "TokenBucket",
    "HttpClient",
    "AbstractExchange",
]
