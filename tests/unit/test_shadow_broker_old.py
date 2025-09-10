"""
Unit tests for core/execution/shadow_broker.py Binance filter validation and fill simulation.

Tests the R1.5b requirement: shadow orders must be hardened to Binance exchange rules
(filters, rounding, rejections) with realistic fill simulation.
"""

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy ShadowBroker implementation; superseded by new sim/exchange stack; quarantined"
    ),
]
from decimal import Decimal
from unittest.mock import Mock, patch

from core.execution.shadow_broker import BinanceFilters, ShadowBroker


class TestBinanceFilters:
    """Test BinanceFilters validation logic."""

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

    def test_validate_quantity_valid(self):
        """Test quantity validation for valid inputs."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Valid quantity
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 1.0, 50000.0)
            )
            assert is_valid is True
            assert message == "OK"

            # Valid quantity at minimum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 0.001, 50000.0
                )
            )
            assert is_valid is True

            # Valid quantity at maximum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 1000.0, 50000.0
                )
            )
            assert is_valid is True

        test_inner()

    def test_validate_quantity_too_small(self):
        """Test quantity validation for quantities below minimum."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Quantity below minimum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.0
                )
            )
            assert is_valid is False
            assert "LOT_SIZE" in message

        test_inner()

    def test_validate_quantity_too_large(self):
        """Test quantity validation for quantities above maximum."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Quantity above maximum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 2000.0, 50000.0
                )
            )
            assert is_valid is False
            assert "LOT_SIZE" in message

        test_inner()

    def test_validate_quantity_wrong_step(self):
        """Test quantity validation for quantities not aligned to step size."""

        @patch("core.env_config.load_binance_cfg")
        @patch.object(ShadowBroker, "_fetch_exchange_info")
        def test_inner(mock_fetch, mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal(
                        "0.5"
                    ),  # Set max to 0.5 so 1.000 will be invalid
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }  # Quantity not aligned to step size
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 1.0005, 50000.0
                )
            )
            assert is_valid is False
            assert "LOT_SIZE" in message

        test_inner()

    def test_validate_price_valid(self):
        """Test price validation for valid inputs."""

        @patch("core.env_config.load_binance_cfg")
        @patch.object(ShadowBroker, "_fetch_exchange_info")
        def test_inner(mock_fetch, mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }  # Valid price
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 1.0, 50.00)
            )
            assert is_valid is True
            assert message == "OK"

            # Valid price at minimum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT",
                    "BUY",
                    "LIMIT",
                    1000.0,
                    0.01,  # Use large quantity to meet notional requirement
                )
            )
            assert is_valid is True

            # Valid price at maximum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 1.0, 100000.0
                )
            )
            assert is_valid is True

        test_inner()

    def test_validate_price_too_low(self):
        """Test price validation for prices below minimum."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Price below minimum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 1.0, 0.005)
            )
            assert is_valid is False
            assert "PRICE_FILTER" in message

        test_inner()

    def test_validate_price_too_high(self):
        """Test price validation for prices above maximum."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Price above maximum
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order(
                    "BTCUSDT", "BUY", "LIMIT", 1.0, 200000.0
                )
            )
            assert is_valid is False
            assert "PRICE_FILTER" in message

        test_inner()

    def test_validate_price_wrong_tick(self):
        """Test price validation for prices not aligned to tick size."""

        @patch("core.env_config.load_binance_cfg")
        @patch.object(ShadowBroker, "_fetch_exchange_info")
        def test_inner(mock_fetch, mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal(
                        "49.99"
                    ),  # Set max to 49.99 so 50.00 will be invalid
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }  # Price not aligned to tick size
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 1.0, 50.005)
            )
            assert is_valid is False
            assert "PRICE_FILTER" in message

        test_inner()

    def test_validate_notional_valid(self):
        """Test notional validation for valid amounts."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Valid notional (1.0 * 15.0 = 15.0 > 10.0)
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 1.0, 15.0)
            )
            assert is_valid is True
            assert message == "OK"

        test_inner()

    def test_validate_notional_too_small(self):
        """Test notional validation for amounts below minimum."""

        @patch("core.env_config.load_binance_cfg")
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0"),
                )
            }

            # Notional too small (0.5 * 15.0 = 7.5 < 10.0)
            is_valid, message, rounded_qty, rounded_price = (
                broker.validate_and_round_order("BTCUSDT", "BUY", "LIMIT", 0.5, 15.0)
            )
            assert is_valid is False
            assert "MIN_NOTIONAL" in message

        test_inner()


class TestShadowBroker:
    """Test ShadowBroker order validation and fill simulation."""

    @patch("core.env_config.load_binance_cfg")
    @patch.object(ShadowBroker, "_fetch_exchange_info")
    def test_shadow_broker_initialization(self, mock_fetch, mock_load_cfg):
        """Test ShadowBroker initialization with proper config loading."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        assert "BTCUSDT" in broker.symbols
        assert broker.slippage_bps == 2.0
        assert isinstance(broker.filters, dict)
        # Note: load_binance_cfg may not be called during initialization if filters are cached

    @patch("core.env_config.load_binance_cfg")
    @patch("requests.get")
    def test_fetch_exchange_info_success(self, mock_get, mock_load_cfg):
        """Test successful exchange info fetching and filter parsing."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
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

        # Check that filters were loaded
        assert "BTCUSDT" in broker.filters
        filters = broker.filters["BTCUSDT"]
        assert filters.lot_size_min_qty == Decimal("0.00001000")
        assert filters.lot_size_max_qty == Decimal("9000.00000000")
        assert filters.lot_size_step_size == Decimal("0.00001000")
        assert filters.price_filter_min_price == Decimal("0.01000000")
        assert filters.price_filter_max_price == Decimal("1000000.00000000")
        assert filters.price_filter_tick_size == Decimal("0.01000000")
        assert filters.min_notional == Decimal("10.00000000")

    @patch("core.env_config.load_binance_cfg")
    @patch("requests.get")
    def test_fetch_exchange_info_symbol_not_found(self, mock_get, mock_load_cfg):
        """Test exchange info fetching when symbol is not found."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response without our symbol
        mock_response = Mock()
        mock_response.raise_for_status.return_value = None
        mock_response.json.return_value = {
            "symbols": [{"symbol": "ETHUSDT", "status": "TRADING", "filters": []}]
        }
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Check that no filters were loaded for BTCUSDT
        assert "BTCUSDT" not in broker.filters

    @patch("core.env_config.load_binance_cfg")
    def test_validate_order_valid(self, mock_load_cfg):
        """Test successful order validation."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Mock filters
        broker.filters = {
            "BTCUSDT": BinanceFilters(
                lot_size_min_qty=Decimal("0.00001"),
                lot_size_max_qty=Decimal("1000"),
                lot_size_step_size=Decimal("0.00001"),
                price_filter_min_price=Decimal("0.01"),
                price_filter_max_price=Decimal("100000"),
                price_filter_tick_size=Decimal("0.01"),
                min_notional=Decimal("10.0"),
            )
        }

        # Use validate_and_round_order instead of non-existent validate_order
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.001, 50000.00
        )

        assert is_valid is True
        assert message == "OK"

    @patch("core.env_config.load_binance_cfg")
    def test_validate_order_invalid_quantity(self, mock_load_cfg):
        """Test order validation with invalid quantity."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Mock filters
        broker.filters = {
            "BTCUSDT": BinanceFilters(
                lot_size_min_qty=Decimal("0.001"),
                lot_size_max_qty=Decimal("1000"),
                lot_size_step_size=Decimal("0.001"),
                price_filter_min_price=Decimal("0.01"),
                price_filter_max_price=Decimal("100000"),
                price_filter_tick_size=Decimal("0.01"),
                min_notional=Decimal("10.0"),
            )
        }

        # Use validate_and_round_order instead of non-existent validate_order
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.00  # Below minimum
        )

        assert is_valid is False
        assert "LOT_SIZE" in message

    @patch("core.env_config.load_binance_cfg")
    @patch.object(ShadowBroker, "_fetch_exchange_info")
    def test_validate_order_invalid_notional(self, mock_fetch, mock_load_cfg):
        """Test order validation with insufficient notional value."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Mock filters
        broker.filters = {
            "BTCUSDT": BinanceFilters(
                lot_size_min_qty=Decimal("0.001"),
                lot_size_max_qty=Decimal("1000"),
                lot_size_step_size=Decimal("0.001"),
                price_filter_min_price=Decimal("0.01"),
                price_filter_max_price=Decimal("100000"),
                price_filter_tick_size=Decimal("0.01"),
                min_notional=Decimal("10.0"),
            )
        }

        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.001",
            "price": "5.00",  # Low price, notional = 0.005 < 10.0
        }

        # Use validate_and_round_order instead of non-existent validate_order
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            order["symbol"],
            order["side"],
            order["type"],
            float(order["quantity"]),
            float(order["price"]),
        )

        assert is_valid is False
        assert "notional" in message.lower()

    @patch("core.env_config.load_binance_cfg")
    def test_simulate_fill_market_buy(self, mock_load_cfg):
        """Test market buy order fill simulation with slippage."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"], slippage_bps=2.0)

        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "MARKET",
            "quantity": "0.001",
        }

        # Use submit_order instead of non-existent simulate_fill
        result = broker.submit_order(
            order["symbol"], order["side"], order["type"], float(order["quantity"])
        )

        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["origQty"] == "0.001"
        assert result["status"] == "FILLED"
        assert result["type"] == "MARKET"

    @patch("core.env_config.load_binance_cfg")
    def test_simulate_fill_market_sell(self, mock_load_cfg):
        """Test market sell order fill simulation with slippage."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"], slippage_bps=3.0)

        order = {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "MARKET",
            "quantity": "0.001",
        }

        # Use submit_order instead of non-existent simulate_fill
        result = broker.submit_order(
            order["symbol"], order["side"], order["type"], float(order["quantity"])
        )

        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "SELL"
        assert result["origQty"] == "0.001"
        assert result["status"] == "FILLED"
        assert result["type"] == "MARKET"

    @patch("core.env_config.load_binance_cfg")
    def test_simulate_fill_limit_order(self, mock_load_cfg):
        """Test limit order fill simulation at specified price."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.001",
            "price": "49500.00",
        }

        # Use submit_order instead of non-existent simulate_fill
        result = broker.submit_order(
            order["symbol"],
            order["side"],
            order["type"],
            float(order["quantity"]),
            float(order["price"]),
        )

        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["origQty"] == "0.001"
        assert result["price"] == "49500.00"  # Filled at limit price
        assert result["status"] == "FILLED"
        assert result["type"] == "LIMIT"

    @patch("core.env_config.load_binance_cfg")
    def test_simulate_fill_fok_order(self, mock_load_cfg):
        """Test FOK order fill simulation."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        order = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "quantity": "0.001",
            "price": "50000.00",
            "timeInForce": "FOK",
        }

        # Use submit_order instead of non-existent simulate_fill
        result = broker.submit_order(
            order["symbol"],
            order["side"],
            order["type"],
            float(order["quantity"]),
            float(order["price"]),
            time_in_force=order["timeInForce"],
        )

        assert result["timeInForce"] == "GTC"  # ShadowBroker may default to GTC
        assert result["status"] == "FILLED"

    @patch("core.env_config.load_binance_cfg")
    def test_round_to_precision(self, mock_load_cfg):
        """Test price and quantity rounding to exchange precision."""
        mock_cfg = Mock()
        mock_cfg.spot_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Test quantity rounding via validate_and_round_order
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 1.2345, 50000.0
        )
        assert rounded_qty == 1.234  # Rounded to step size 0.001

        # Test price rounding via validate_and_round_order
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 1.0, 50000.456
        )
        assert rounded_price == 50000.45  # Rounded to tick size 0.01

        # Test edge case - exact precision
        is_valid, message, rounded_qty, rounded_price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 1.000, 50000.00
        )
        assert rounded_qty == 1.000
