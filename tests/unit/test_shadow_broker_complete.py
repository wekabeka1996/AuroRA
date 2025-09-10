"""
Повне тестування ShadowBroker з 100% покриттям
"""

import pytest

# Quarantine: legacy ShadowBroker tests superseded by router_v2/sim.
pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy ShadowBroker; superseded by router_v2 & sim; quarantined"
    ),
]
from decimal import Decimal
from unittest.mock import MagicMock, Mock, patch

from core.execution.shadow_broker import BinanceFilters, OrderReject, ShadowBroker


class TestShadowBrokerComplete:
    """Повне тестування ShadowBroker для досягнення 100% покриття"""

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_init_with_symbols(self, mock_load_cfg):
        """Тест ініціалізації з символами"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            assert "BTCUSDT" in broker.filters
            assert isinstance(broker.filters["BTCUSDT"], BinanceFilters)
            assert broker.symbols == ["BTCUSDT"]
            assert broker.slippage_bps == 2.0

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_init_with_custom_slippage(self, mock_load_cfg):
        """Тест ініціалізації з кастомним slippage"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"], slippage_bps=5.0)

            assert broker.slippage_bps == 5.0

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_init_api_failure_fallback(self, mock_load_cfg):
        """Тест fallback при невдачі API"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get", side_effect=Exception("API Error")):
            broker = ShadowBroker(["BTCUSDT"])

            # Повинно встановити дефолтні фільтри
            assert "BTCUSDT" in broker.filters
            filters = broker.filters["BTCUSDT"]
            assert filters.lot_size_min_qty == Decimal("0.001")
            assert filters.min_notional == Decimal("10.0")

    def test_binance_filters_dataclass(self):
        """Тест BinanceFilters dataclass"""
        filters = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("100.0"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000.0"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0"),
        )

        assert filters.lot_size_min_qty == Decimal("0.001")
        assert filters.price_filter_tick_size == Decimal("0.01")
        assert filters.min_notional == Decimal("10.0")

    def test_order_reject_dataclass(self):
        """Тест OrderReject dataclass"""
        reject = OrderReject("LOT_SIZE", "Quantity too small")

        assert reject.reason == "LOT_SIZE"
        assert reject.details == "Quantity too small"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_round_quantity(self, mock_load_cfg):
        """Тест округлення кількості"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Тест округлення - 0.00123456 повинно округлитися до 0.001 (step_size = 0.001)
            result = broker._round_quantity("BTCUSDT", Decimal("0.00123456"))
            assert result == Decimal("0.001")  # Округлено вниз до step_size

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_round_price(self, mock_load_cfg):
        """Тест округлення ціни"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Тест округлення - 50000.123456 повинно округлитися до 50000.12 (tick_size = 0.01)
            result = broker._round_price("BTCUSDT", Decimal("50000.123456"))
            assert result == Decimal("50000.12")  # Округлено до tick_size

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_valid(self, mock_load_cfg):
        """Тест валідації валідного ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Валідний ордер
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("50000.0")
            )
            assert result is None  # Без помилок

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_invalid_quantity(self, mock_load_cfg):
        """Тест валідації ордера з невалідною кількістю"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Занадто мала кількість
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.0001"), Decimal("50000.0")
            )
            assert result is not None
            assert result.reason == "LOT_SIZE"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_invalid_price(self, mock_load_cfg):
        """Тест валідації ордера з невалідною ціною"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Занадто низька ціна
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("0.001")
            )
            assert result is not None
            assert result.reason == "PRICE_FILTER"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_invalid_notional(self, mock_load_cfg):
        """Тест валідації ордера з невалідним notional"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {
                                "filterType": "MIN_NOTIONAL",
                                "minNotional": "1000.0",
                            },  # Високий min notional
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Занадто малий notional
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("1.0")
            )
            assert result is not None
            assert result.reason == "MIN_NOTIONAL"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_unknown_symbol(self, mock_load_cfg):
        """Тест валідації ордера з невідомим символом"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Невідомий символ
            result = broker._validate_order(
                "UNKNOWN", "BUY", "LIMIT", Decimal("0.001"), Decimal("50000.0")
            )
            assert result is not None
            assert result.reason == "UNKNOWN_SYMBOL"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_generate_order_id(self, mock_load_cfg):
        """Тест генерації ID ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                order_id = broker._generate_order_id()
                assert "SHADOW_1234567890123_" in order_id
                assert broker.order_counter == 1

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_simulate_fill_market_order(self, mock_load_cfg):
        """Тест симуляції виконання market ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"], slippage_bps=2.0)

            with patch("time.time", return_value=1234567890.123):
                result = broker._simulate_fill(
                    "BTCUSDT", "BUY", "MARKET", Decimal("0.001")
                )

                assert result["symbol"] == "BTCUSDT"
                assert result["status"] == "FILLED"
                assert result["type"] == "MARKET"
                assert result["side"] == "BUY"
                assert "orderId" in result
                assert "fills" in result

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_simulate_fill_limit_order(self, mock_load_cfg):
        """Тест симуляції виконання limit ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                result = broker._simulate_fill(
                    "BTCUSDT", "SELL", "LIMIT", Decimal("0.001"), Decimal("50000.0")
                )

                assert result["symbol"] == "BTCUSDT"
                assert result["status"] == "FILLED"
                assert result["type"] == "LIMIT"
                assert result["side"] == "SELL"
                assert result["price"] == "50000.0"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    @patch("core.execution.shadow_broker.OrderLoggers")
    def test_log_order_event(self, mock_loggers, mock_load_cfg):
        """Тест логування події ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True) as mock_open:
                    mock_file = MagicMock()
                    mock_open.return_value.__enter__.return_value = mock_file

                    broker._log_order_event(
                        "FILLED",
                        "BTCUSDT",
                        "BUY",
                        "MARKET",
                        Decimal("0.001"),
                        Decimal("50000.0"),
                        "SUCCESS",
                    )

                    # Перевіряємо що файл було відкрито для запису
                    mock_open.assert_called_with("logs/shadow_orders.jsonl", "a")
                    # Перевіряємо що було записано JSON
                    mock_file.write.assert_called_once()
                    written_data = mock_file.write.call_args[0][0]
                    assert "FILLED" in written_data
                    assert "BTCUSDT" in written_data

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_market_success(self, mock_load_cfg):
        """Тест успішного market ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True):
                    result = broker.submit_order("BTCUSDT", "BUY", "MARKET", 0.001)

                    assert result["status"] == "FILLED"
                    assert result["symbol"] == "BTCUSDT"
                    assert result["side"] == "BUY"
                    assert result["type"] == "MARKET"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_limit_success(self, mock_load_cfg):
        """Тест успішного limit ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True):
                    result = broker.submit_order(
                        "BTCUSDT", "SELL", "LIMIT", 0.001, 50000.0
                    )

                    assert result["status"] == "FILLED"
                    assert result["symbol"] == "BTCUSDT"
                    assert result["side"] == "SELL"
                    assert result["type"] == "LIMIT"
                    assert result["price"] == "50000.00"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_rejection(self, mock_load_cfg):
        """Тест відхилення ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "MIN_NOTIONAL",
                                "minNotional": "1000.0",
                            },  # Високий min notional
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True):
                    result = broker.submit_order(
                        "BTCUSDT", "BUY", "LIMIT", 0.001, 1.0
                    )  # Занадто малий notional

                    assert "code" in result
                    assert result["code"] == -1013
                    assert "Filter failure" in result["msg"]

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_ioc_partial_fill(self, mock_load_cfg):
        """Тест IOC ордера з частковим виконанням"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True):
                    # Великий IOC ордер - симулюється часткове виконання
                    result = broker.submit_order(
                        "BTCUSDT", "BUY", "LIMIT", 2.0, 50000.0, "IOC"
                    )

                    assert result["status"] == "FILLED"
                    # Для IOC з великою кількістю може бути часткове виконання
                    executed_qty = Decimal(result["executedQty"])
                    assert executed_qty <= Decimal("2.0")

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_fok_rejection(self, mock_load_cfg):
        """Тест FOK ордера з відхиленням"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                with patch("builtins.open", create=True):
                    # Великий FOK ордер - симулюється відхилення
                    result = broker.submit_order(
                        "BTCUSDT", "BUY", "LIMIT", 20.0, 50000.0, "FOK"
                    )

                    assert "code" in result
                    assert result["code"] == -2010
                    assert "insufficient balance" in result["msg"]

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_get_filters(self, mock_load_cfg):
        """Тест отримання фільтрів"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            filters = broker.get_filters("BTCUSDT")
            assert filters is not None
            assert isinstance(filters, BinanceFilters)

            # Невідомий символ
            unknown_filters = broker.get_filters("UNKNOWN")
            assert unknown_filters is None

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_and_round_order(self, mock_load_cfg):
        """Тест валідації та округлення ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Валідний ордер
            is_valid, message, qty, price = broker.validate_and_round_order(
                "BTCUSDT", "BUY", "LIMIT", 0.001234, 50000.123
            )
            assert is_valid is True
            assert message == "OK"
            assert qty == 0.001  # Округлено
            assert price == 50000.12  # Округлено

            # Невалідний ордер
            is_valid, message, qty, price = broker.validate_and_round_order(
                "BTCUSDT", "BUY", "LIMIT", 0.0001, 50000.0
            )
            assert is_valid is False
            assert "LOT_SIZE" in message

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_edge_case_min_values(self, mock_load_cfg):
        """Тест крайніх випадків з мінімальними значеннями"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Мінімальна кількість
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("10000.0")
            )
            assert result is None

            # Мінімальна ціна
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("10000.0")
            )
            assert result is None

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_edge_case_max_values(self, mock_load_cfg):
        """Тест крайніх випадків з максимальними значеннями"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Максимальна кількість
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("100.0"), Decimal("10000.0")
            )
            assert result is None

            # Максимальна ціна
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("100000.0")
            )
            assert result is None

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_multiple_symbols(self, mock_load_cfg):
        """Тест роботи з множинними символами"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    },
                    {
                        "symbol": "ETHUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.01",
                                "maxQty": "1000.0",
                                "stepSize": "0.01",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.1",
                                "maxPrice": "10000.0",
                                "tickSize": "0.1",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    },
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT", "ETHUSDT"])

            # Перевіряємо що обидва символи ініціалізовані
            assert "BTCUSDT" in broker.filters
            assert "ETHUSDT" in broker.filters

            # Перевіряємо різні фільтри для різних символів
            btc_filters = broker.filters["BTCUSDT"]
            eth_filters = broker.filters["ETHUSDT"]

            assert btc_filters.lot_size_min_qty == Decimal("0.001")
            assert eth_filters.lot_size_min_qty == Decimal("0.01")

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_api_error_handling(self, mock_load_cfg):
        """Тест обробки помилок API"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Тест різних типів помилок API
        with patch("requests.get", side_effect=Exception("Connection timeout")):
            broker = ShadowBroker(["BTCUSDT"])
            # Повинно працювати з дефолтними фільтрами
            assert "BTCUSDT" in broker.filters

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.raise_for_status.side_effect = Exception("HTTP 500")
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])
            # Повинно працювати з дефолтними фільтрами
            assert "BTCUSDT" in broker.filters

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_trading_disabled_symbol(self, mock_load_cfg):
        """Тест символу з вимкненою торгівлею"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "BREAK",  # Не TRADING
                        "filters": [],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Символ не повинен бути ініціалізований
            assert "BTCUSDT" not in broker.filters

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_round_quantity_unknown_symbol(self, mock_load_cfg):
        """Тест округлення кількості для невідомого символу"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Невідомий символ - повинно повернути без змін
            result = broker._round_quantity("UNKNOWN", Decimal("0.00123456"))
            assert result == Decimal("0.00123456")  # Без округлення

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_round_price_unknown_symbol(self, mock_load_cfg):
        """Тест округлення ціни для невідомого символу"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {"symbols": []}
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Невідомий символ - повинно повернути без змін
            result = broker._round_price("UNKNOWN", Decimal("50000.123456"))
            assert result == Decimal("50000.123456")  # Без округлення

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_max_quantity(self, mock_load_cfg):
        """Тест валідації ордера з максимальною кількістю"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Занадто велика кількість
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("200.0"), Decimal("50000.0")
            )
            assert result is not None
            assert result.reason == "LOT_SIZE"

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_price_tick_size(self, mock_load_cfg):
        """Тест валідації ордера з невірним tick size ціни"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Ціна не кратна tick_size (0.015 не кратно 0.01)
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("0.015")
            )
            assert result is not None
            assert result.reason == "PRICE_FILTER"
            assert "tick size" in result.details

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_quantity_step_size(self, mock_load_cfg):
        """Тест валідації ордера з невірним step size кількості"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Кількість не кратна step_size (0.0015 не кратно 0.001)
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.0015"), Decimal("50000.0")
            )
            assert result is not None
            assert result.reason == "LOT_SIZE"
            assert "step size" in result.details

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_fetch_exchange_info_skip_symbol(self, mock_load_cfg):
        """Тест пропуску символу що не в списку"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    },
                    {
                        "symbol": "ETHUSDT",  # Не в списку symbols
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.01",
                                "maxQty": "1000.0",
                                "stepSize": "0.01",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.1",
                                "maxPrice": "10000.0",
                                "tickSize": "0.1",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    },
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])  # Тільки BTCUSDT в списку

            # Повинно ініціалізувати тільки BTCUSDT
            assert "BTCUSDT" in broker.filters
            assert "ETHUSDT" not in broker.filters  # ETHUSDT пропущено

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_and_round_order_invalid(self, mock_load_cfg):
        """Тест validate_and_round_order з невалідним ордером"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Невалідний ордер (занадто мала кількість)
            result = broker.validate_and_round_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.0001"), Decimal("50000.0")
            )
            assert result is not None  # Повинно повернути кортеж для невалідного ордера
            is_valid, message, qty, price = result
            assert is_valid is False
            assert "LOT_SIZE" in message

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_unknown_symbol(self, mock_load_cfg):
        """Тест валідації ордера з невідомим символом"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Невідомий символ
            result = broker._validate_order(
                "UNKNOWN", "BUY", "LIMIT", Decimal("0.001"), Decimal("50000.0")
            )
            assert result is not None
            assert result.reason == "UNKNOWN_SYMBOL"
            assert "No filters available" in result.details

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_validate_order_price_max(self, mock_load_cfg):
        """Тест валідації ордера з ціною вище максимальної"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Ціна вище максимальної
            result = broker._validate_order(
                "BTCUSDT", "BUY", "LIMIT", Decimal("0.001"), Decimal("200000.0")
            )
            assert result is not None
            assert result.reason == "PRICE_FILTER"
            assert "Price 200000.0 > max" in result.details

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_simulate_fill_sell_market(self, mock_load_cfg):
        """Тест симуляції виконання SELL market ордера"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            with patch("time.time", return_value=1234567890.123):
                result = broker._simulate_fill(
                    "BTCUSDT", "SELL", "MARKET", Decimal("0.001")
                )

                assert result["status"] == "FILLED"
                assert result["side"] == "SELL"
                assert result["type"] == "MARKET"
                # Для SELL market ордера ціна повинна бути нижчою через slippage
                fill_price = Decimal(result["price"])
                expected_price = Decimal("50000") * (
                    1 - Decimal(broker.slippage_bps) / Decimal(10000)
                )
                assert fill_price == expected_price

    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_log_order_event_exception_handling(self, mock_load_cfg):
        """Тест обробки винятків в _log_order_event"""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        with patch("requests.get") as mock_get:
            mock_response = Mock()
            mock_response.json.return_value = {
                "symbols": [
                    {
                        "symbol": "BTCUSDT",
                        "status": "TRADING",
                        "filters": [
                            {
                                "filterType": "LOT_SIZE",
                                "minQty": "0.001",
                                "maxQty": "100.0",
                                "stepSize": "0.001",
                            },
                            {
                                "filterType": "PRICE_FILTER",
                                "minPrice": "0.01",
                                "maxPrice": "100000.0",
                                "tickSize": "0.01",
                            },
                            {"filterType": "MIN_NOTIONAL", "minNotional": "10.0"},
                        ],
                    }
                ]
            }
            mock_response.raise_for_status.return_value = None
            mock_get.return_value = mock_response

            broker = ShadowBroker(["BTCUSDT"])

            # Симулюємо помилку при відкритті файлу
            with patch("builtins.open", side_effect=Exception("File write error")):
                # Це не повинно викликати виняток
                broker._log_order_event(
                    "FILLED",
                    "BTCUSDT",
                    "BUY",
                    "MARKET",
                    Decimal("0.001"),
                    Decimal("50000.0"),
                    "SUCCESS",
                )
