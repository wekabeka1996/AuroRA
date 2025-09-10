"""
Exchange Adapter Smoke Tests
============================

Minimal tests for exchange adapters without network calls.
Tests quantization, validation, and idempotency key generation.
"""

import pytest

from core.execution.exchange.common import (
    OrderRequest,
    OrderType,
    Side,
    ValidationError,
    make_idempotency_key,
)
from core.execution.exchange.binance import BinanceExchange
from core.execution.exchange.gate import GateExchange


class MockHttpClient:
    """Mock HTTP client for testing without network calls."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []

    def request(self, method, url, *, params=None, headers=None, json=None):
        self.requests.append((method, url, params, headers, json))
        # Return mock response based on URL pattern
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        return {}


def test_binance_symbol_info_offline():
    """Test Binance symbol info without HTTP client."""
    ex = BinanceExchange(api_key="test", api_secret="secret")

    info = ex.get_symbol_info("BTCUSDT")
    assert info.symbol == "BTCUSDT"
    assert info.base == "BTC"
    assert info.quote == "USDT"
    assert info.tick_size == 0.01
    assert info.step_size == 0.001
    assert info.min_qty == 0.001
    assert info.min_notional == 5.0


def test_gate_symbol_info_offline():
    """Test Gate symbol info without HTTP client."""
    ex = GateExchange(api_key="test", api_secret="secret")

    info = ex.get_symbol_info("BTC_USDT")
    assert info.symbol == "BTCUSDT"
    assert info.base == "BTC"
    assert info.quote == "USDT"
    assert info.tick_size == 0.01
    assert info.step_size == 0.001
    assert info.min_qty == 0.001
    assert info.min_notional == 5.0


def test_binance_quantization():
    """Test Binance order quantization and validation."""
    ex = BinanceExchange(api_key="test", api_secret="secret")

    # Test LIMIT order quantization
    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.123456789,
        price=50000.123456789,
    )

    clean = ex.validate_order(req)
    assert clean.quantity == 0.123  # quantized to step_size
    assert clean.price == 50000.12  # quantized to tick_size


def test_gate_quantization():
    """Test Gate order quantization and validation."""
    ex = GateExchange(api_key="test", api_secret="secret")

    # Test LIMIT order quantization
    req = OrderRequest(
        symbol="BTC_USDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.123456789,
        price=50000.123456789,
    )

    clean = ex.validate_order(req)
    assert clean.quantity == 0.123  # quantized to step_size
    assert clean.price == 50000.12  # quantized to tick_size


def test_min_notional_validation():
    """Test minimum notional validation."""
    ex = BinanceExchange(api_key="test", api_secret="secret")

    # Order with too small notional should fail
    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.001,  # meets min_qty but notional too small
        price=0.01,      # very low price
    )

    with pytest.raises(ValidationError, match="notional"):
        ex.validate_order(req)


def test_idempotency_key_generation():
    """Test deterministic idempotency key generation."""
    payload1 = {"s": "BTCUSDT", "sd": "BUY", "t": "MARKET", "q": 0.001, "p": ""}
    payload2 = {"s": "BTCUSDT", "sd": "BUY", "t": "MARKET", "q": 0.001, "p": ""}

    key1 = make_idempotency_key("oid", payload1)
    key2 = make_idempotency_key("oid", payload2)

    assert key1 == key2  # same payload should generate same key
    assert len(key1) == 28  # prefix + 24 hex chars
    assert key1.startswith("oid_")


def test_symbol_normalization():
    """Test symbol normalization across exchanges."""
    binance_ex = BinanceExchange(api_key="test", api_secret="secret")
    gate_ex = GateExchange(api_key="test", api_secret="secret")

    # Binance normalizes by removing separators and uppercasing
    assert binance_ex.normalize_symbol("btc-usdt") == "BTCUSDT"
    assert binance_ex.normalize_symbol("BTC/USDT") == "BTCUSDT"

    # Gate uses same normalization
    assert gate_ex.normalize_symbol("btc_usdt") == "BTCUSDT"
    assert gate_ex.normalize_symbol("BTC-USDT") == "BTCUSDT"


def test_client_order_id_generation():
    """Test client order ID generation in adapters."""
    ex = BinanceExchange(api_key="test", api_secret="secret")

    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        quantity=0.001,
    )

    # Should generate deterministic client ID
    clean = ex.validate_order(req)
    assert clean.client_order_id is not None
    assert clean.client_order_id.startswith("oid_")
    assert len(clean.client_order_id) == 28