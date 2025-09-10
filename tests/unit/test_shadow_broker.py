# -*- coding: utf-8 -*-
"""
Unit tests for ShadowBroker class.
Tests shadow order validation and simulation.
"""
import unittest

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy ShadowBroker tests; replaced by core/execution/sim and router_v2; quarantined"
    ),
]
from decimal import Decimal
from unittest.mock import Mock, patch

from core.execution.shadow_broker import BinanceFilters, OrderReject, ShadowBroker


class TestBinanceFilters(unittest.TestCase):
    """Test BinanceFilters dataclass."""

    def test_binance_filters_creation(self):
        """Test valid BinanceFilters creation."""
        filters = BinanceFilters(
            lot_size_min_qty=Decimal("0.00001"),
            lot_size_max_qty=Decimal("100000"),
            lot_size_step_size=Decimal("0.00001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("1000000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        assert filters.lot_size_min_qty == Decimal("0.00001")
        assert filters.lot_size_max_qty == Decimal("100000")
        assert filters.lot_size_step_size == Decimal("0.00001")
        assert filters.price_filter_min_price == Decimal("0.01")
        assert filters.price_filter_max_price == Decimal("1000000")
        assert filters.price_filter_tick_size == Decimal("0.01")
        assert filters.min_notional == Decimal("10.0")


class TestShadowBroker(unittest.TestCase):
    """Test ShadowBroker implementation."""

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_shadow_broker_initialization(self, mock_load_cfg, mock_get):
        """Test ShadowBroker initialization with proper config loading."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        assert "BTCUSDT" in broker.symbols
        assert broker.slippage_bps == 2.0
        mock_load_cfg.assert_called_once()

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_shadow_broker_with_custom_slippage(self, mock_load_cfg, mock_get):
        """Test ShadowBroker initialization with custom slippage config."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["ETHUSDT"], slippage_bps=5.0)

        assert "ETHUSDT" in broker.symbols
        assert broker.slippage_bps == 5.0
        mock_load_cfg.assert_called_once()

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_get_filters(self, mock_load_cfg, mock_get):
        """Test getting filters for symbol."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "symbols": [
                {
                    "symbol": "BTCUSDT",
                    "status": "TRADING",
                    "filters": [
                        {
                            "filterType": "LOT_SIZE",
                            "minQty": "0.00001000",
                            "maxQty": "9000.00000000",
                            "stepSize": "0.00001000",
                        },
                        {
                            "filterType": "PRICE_FILTER",
                            "minPrice": "0.01000000",
                            "maxPrice": "1000000.00000000",
                            "tickSize": "0.01000000",
                        },
                        {"filterType": "MIN_NOTIONAL", "minNotional": "10.00000000"},
                    ],
                }
            ]
        }
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])
        filters = broker.get_filters("BTCUSDT")

        assert filters is not None
        assert filters.lot_size_min_qty == Decimal("0.00001000")
        assert filters.lot_size_max_qty == Decimal("9000.00000000")
        assert filters.lot_size_step_size == Decimal("0.00001000")
        assert filters.min_notional == Decimal("10.00000000")

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_and_round_order_valid(self, mock_load_cfg, mock_get):
        """Test successful order validation and rounding."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.00001"),
            lot_size_max_qty=Decimal("9000"),
            lot_size_step_size=Decimal("0.00001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("1000000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 1.0, 50000.0
        )

        assert is_valid is True
        assert message == "OK"
        assert qty == 1.0
        assert price == 50000.0

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_and_round_order_invalid_quantity(self, mock_load_cfg, mock_get):
        """Test order validation with invalid quantity."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        # Test quantity too small
        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.0
        )

        assert is_valid is False
        assert "LOT_SIZE" in message
        assert "Quantity" in message

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_and_round_order_invalid_notional(self, mock_load_cfg, mock_get):
        """Test order validation with insufficient notional value."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        # Test insufficient notional (0.001 * 1.0 = 0.001 < 10.0)
        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.001, 1.0
        )

        assert is_valid is False
        assert "MIN_NOTIONAL" in message

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_market_buy(self, mock_load_cfg, mock_get):
        """Test market buy order submission with slippage simulation."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"], slippage_bps=2.0)

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        result = broker.submit_order("BTCUSDT", "BUY", "MARKET", 1.0)

        assert result["status"] == "FILLED"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["type"] == "MARKET"
        assert result["executedQty"] == "1.000"  # Fixed expected format
        assert "orderId" in result
        assert "fills" in result

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_limit_order(self, mock_load_cfg, mock_get):
        """Test limit order submission at specified price."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        result = broker.submit_order("BTCUSDT", "BUY", "LIMIT", 1.0, 50000.0)

        assert result["status"] == "FILLED"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["type"] == "LIMIT"
        assert result["executedQty"] == "1.000"  # Fixed expected format
        assert float(result["fills"][0]["price"]) == 50000.0

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_validation_failure(self, mock_load_cfg, mock_get):
        """Test order rejection due to validation failure."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        # Submit order with invalid quantity
        result = broker.submit_order("BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.0)

        # Fixed expected format for validation failure
        assert "code" in result
        assert result["code"] == -1013
        assert "Filter failure" in result["msg"]
        assert "LOT_SIZE" in result["msg"]


if __name__ == "__main__":
    unittest.main()
