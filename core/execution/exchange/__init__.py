# Exchange adapters for Aurora
# Provides unified interface for different exchanges (Binance, Gate.io, etc.)

from .common import (
    AbstractExchange,
    ExchangeError,
    ValidationError,
    RateLimitError,
    Side,
    OrderType,
    TimeInForce,
    SymbolInfo,
    OrderRequest,
    Fill,
    OrderResult,
    apply_symbol_filters,
    make_idempotency_key,
    TokenBucket,
    HttpClient,
)

from .binance import BinanceExchange
from .gate import GateExchange

__all__ = [
    # Common primitives
    "AbstractExchange",
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
    "apply_symbol_filters",
    "make_idempotency_key",
    "TokenBucket",
    "HttpClient",
    # Exchange adapters
    "BinanceExchange",
    "GateExchange",
]