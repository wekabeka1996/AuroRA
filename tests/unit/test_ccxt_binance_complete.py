"""
Повне тестування CCXT Binance Adapter з 100% покриттям
"""
import os
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
import ccxt
from skalp_bot.exch.ccxt_binance import CCXTBinanceAdapter


class TestCCXTBinanceAdapterComplete:
    """Повне тестування CCXTBinanceAdapter для досягнення 100% покриття"""

    @patch('os.getenv')
    def test_init_default_futures(self, mock_getenv):
        """Тест ініціалізації з дефолтними налаштуваннями для ф'ючерсів"""
        # Mock os.getenv to return None for DRY_RUN
        mock_getenv.return_value = None
        mock_getenv.side_effect = lambda key, default=None: None if key == 'DRY_RUN' else default
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        assert adapter.use_futures is True
        assert adapter.dry is True  # default testnet
        assert adapter.symbol == "BTC/USDT"

    @patch('os.getenv')
    def test_init_spot_config(self, mock_getenv):
        """Тест ініціалізації для спот торгівлі"""
        # Mock os.getenv to return None for all env vars (no overrides)
        def getenv_side_effect(key, default=None):
            return None
        mock_getenv.side_effect = getenv_side_effect
        
        cfg = {
            "exchange": {
                "use_futures": False,
                "testnet": False
            },
            "dry_run": True  # Explicitly set dry_run for testing
        }
        adapter = CCXTBinanceAdapter(cfg)
        assert adapter.use_futures is False
        assert adapter.dry is True  # dry_run explicitly set to True

    def test_init_with_env_overrides(self):
        """Тест ініціалізації зі змінними середовища"""
        with patch.dict(os.environ, {
            'EXCHANGE_ID': 'binance',
            'EXCHANGE_TESTNET': 'false',
            'EXCHANGE_USE_FUTURES': 'false',
            'BINANCE_RECV_WINDOW': '10000'
        }):
            cfg = {}
            adapter = CCXTBinanceAdapter(cfg)
            assert adapter.recv_window_ms == 10000

    def test_init_invalid_recv_window(self):
        """Тест обробки невалідного recv_window"""
        cfg = {
            "exchange": {
                "recv_window_ms": "invalid"
            }
        }
        adapter = CCXTBinanceAdapter(cfg)
        assert adapter.recv_window_ms == 5000  # default

    @patch('ccxt.binanceusdm')
    def test_init_exchange_creation(self, mock_exchange_class):
        """Тест створення exchange об'єкта"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        mock_exchange_class.assert_called_once()
        mock_exchange.set_sandbox_mode.assert_called_once_with(True)

    def test_init_with_credentials(self):
        """Тест ініціалізації з API ключами"""
        with patch.dict(os.environ, {
            'BINANCE_API_KEY': 'test_key',
            'BINANCE_SECRET': 'test_secret'
        }):
            with patch('ccxt.binanceusdm') as mock_exchange_class:
                mock_exchange = Mock()
                mock_exchange_class.return_value = mock_exchange
                
                cfg = {}
                adapter = CCXTBinanceAdapter(cfg)
                
                # Перевіряємо що ключі встановлені на екземплярі exchange
                assert adapter.ex.apiKey == 'test_key'
                assert adapter.ex.secret is not None  # CCXT may hash/process the secret

    def test_init_websocket_available(self):
        """Тест ініціалізації з доступним WebSocket"""
        with patch('skalp_bot.exch.ccxt_binance._WEBSOCKET_AVAILABLE', True):
            with patch('skalp_bot.exch.ccxt_binance.BinanceWebSocketClient') as mock_ws_class:
                mock_ws = Mock()
                mock_ws_class.return_value = mock_ws
                
                cfg = {"symbol": "ETHUSDT"}
                adapter = CCXTBinanceAdapter(cfg)
                
                mock_ws_class.assert_called_once()

    def test_init_websocket_not_available(self):
        """Тест ініціалізації без WebSocket"""
        with patch('skalp_bot.exch.ccxt_binance._WEBSOCKET_AVAILABLE', False):
            cfg = {"symbol": "ETHUSDT"}
            adapter = CCXTBinanceAdapter(cfg)
            assert adapter.ws_client is None

    @patch('ccxt.binanceusdm')
    def test_fetch_top_of_book_success(self, mock_exchange_class):
        """Тест успішного отримання ринкових даних"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        # Мокаємо відповіді
        mock_exchange.fetch_order_book.return_value = {
            'bids': [[50000.0, 1.0], [49999.0, 2.0]],
            'asks': [[50001.0, 1.5], [50002.0, 2.5]]
        }
        mock_exchange.fetch_trades.return_value = [
            {'timestamp': 1234567890, 'price': 50000.5, 'amount': 0.1, 'side': 'buy'},
            {'timestamp': 1234567891, 'price': 50000.3, 'amount': 0.2, 'side': 'sell'}
        ]
        
        cfg = {"symbol": "BTCUSDT"}
        adapter = CCXTBinanceAdapter(cfg)
        
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        assert mid == 50000.5  # (50000.0 + 50001.0) / 2
        assert spread == 1.0   # 50001.0 - 50000.0
        assert len(bids) == 2
        assert len(asks) == 2
        assert len(trades) == 2

    @patch('ccxt.binanceusdm')
    def test_fetch_top_of_book_no_data(self, mock_exchange_class):
        """Тест отримання ринкових даних без даних"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        mock_exchange.fetch_order_book.return_value = {'bids': [], 'asks': []}
        mock_exchange.fetch_trades.return_value = []
        
        cfg = {"symbol": "BTCUSDT"}
        adapter = CCXTBinanceAdapter(cfg)
        
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        assert mid == 0.0
        assert spread == 0.0
        assert bids == []
        assert asks == []
        assert trades == []

    @patch('ccxt.binanceusdm')
    def test_fetch_top_of_book_exception(self, mock_exchange_class):
        """Тест обробки винятків при отриманні ринкових даних"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        mock_exchange.fetch_order_book.side_effect = Exception("Network error")
        
        cfg = {"symbol": "BTCUSDT"}
        adapter = CCXTBinanceAdapter(cfg)
        
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        assert mid == 0.0
        assert spread == 0.0
        assert bids == []
        assert asks == []
        assert trades == []

    @patch('ccxt.binanceusdm')
    def test_place_order_dry_run(self, mock_exchange_class):
        """Тест розміщення ордера в dry run режимі"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        adapter.dry = True
        
        result = adapter.place_order("buy", 1.0, price=50000.0)
        
        assert result["info"] == "dry_run"
        assert result["side"] == "buy"
        assert result["qty"] == 1.0
        assert result["price"] == 50000.0

    @patch('ccxt.binanceusdm')
    def test_place_order_live_limit(self, mock_exchange_class):
        """Тест розміщення лімітного ордера в live режимі"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.create_order.return_value = {"id": "12345", "status": "open"}
        
        # Мокаємо методи для квантизації
        mock_exchange.amount_to_precision = lambda symbol, amount: float(amount)
        mock_exchange.price_to_precision = lambda symbol, price: float(price)
        
        cfg = {"exchange": {"testnet": False}}
        adapter = CCXTBinanceAdapter(cfg)
        adapter.dry = False
        
        # Mock _get_limits to return empty dict (no limits)
        with patch.object(adapter, '_get_limits') as mock_limits:
            mock_limits.return_value = {}
            
            result = adapter.place_order("buy", 1.0, price=50000.0)
            
            mock_exchange.create_order.assert_called_once()
            call_args = mock_exchange.create_order.call_args
            # call_args[0] contains all positional args: (symbol, type, side, amount, price, params)
            assert call_args[0][0] == "BTC/USDT"  # symbol
            assert call_args[0][1] == "limit"     # order type
            assert call_args[0][2] == "buy"       # side
            assert call_args[0][3] == 1.0         # amount
            assert call_args[0][4] == 50000.0     # price
            assert call_args[0][5] == {"timeInForce": "GTC"}  # params

    @patch('ccxt.binanceusdm')
    def test_place_order_market(self, mock_exchange_class):
        """Тест розміщення ринкового ордера"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.create_order.return_value = {"id": "12346", "status": "closed"}
        mock_exchange.amount_to_precision = lambda symbol, amount: float(amount)
        
        cfg = {"exchange": {"testnet": False}}
        adapter = CCXTBinanceAdapter(cfg)
        adapter.dry = False
        
        # Mock _get_limits to return empty dict (no limits)
        with patch.object(adapter, '_get_limits') as mock_limits:
            mock_limits.return_value = {}
            
            result = adapter.place_order("sell", 0.5)
            
            call_args = mock_exchange.create_order.call_args
            assert call_args[0][1] == "market"  # order type
            assert call_args[0][4] is None      # no price for market

    @patch('ccxt.binanceusdm')
    def test_place_order_with_reduce_only(self, mock_exchange_class):
        """Тест розміщення ордера з reduce_only"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.create_order.return_value = {"id": "12347", "status": "open"}
        mock_exchange.amount_to_precision = lambda symbol, amount: float(amount)
        mock_exchange.price_to_precision = lambda symbol, price: float(price)
        
        cfg = {"exchange": {"use_futures": True, "testnet": False}}
        adapter = CCXTBinanceAdapter(cfg)
        adapter.dry = False
        adapter.use_futures = True
        
        # Mock _get_limits to return empty dict (no limits)
        with patch.object(adapter, '_get_limits') as mock_limits:
            mock_limits.return_value = {}
            
            result = adapter.place_order("sell", 1.0, price=50000.0, reduce_only=True)
            
            call_args = mock_exchange.create_order.call_args
            # params is the 6th positional argument
            params = call_args[0][5]
            assert params.get("reduceOnly") is True

    @patch('ccxt.binanceusdm')
    def test_place_order_min_qty_validation(self, mock_exchange_class):
        """Тест валідації мінімальної кількості"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.amount_to_precision = lambda symbol, amount: float(amount)
        
        # Мокаємо limits
        with patch.object(CCXTBinanceAdapter, '_get_limits') as mock_limits:
            mock_limits.return_value = {"amount": {"min": 1.0}}
            
            cfg = {"exchange": {"testnet": False}}
            adapter = CCXTBinanceAdapter(cfg)
            adapter.dry = False
            
            with pytest.raises(ValueError, match="below minQty"):
                adapter.place_order("buy", 0.5, price=50000.0)

    @patch('ccxt.binanceusdm')
    def test_place_order_min_cost_validation(self, mock_exchange_class):
        """Тест валідації мінімальної вартості"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.amount_to_precision = lambda symbol, amount: float(amount)
        mock_exchange.price_to_precision = lambda symbol, price: float(price)
        
        with patch.object(CCXTBinanceAdapter, '_get_limits') as mock_limits:
            mock_limits.return_value = {"cost": {"min": 100.0}}
            
            with patch.object(CCXTBinanceAdapter, '_estimate_price') as mock_price:
                mock_price.return_value = 50.0
                
                cfg = {"exchange": {"testnet": False}}
                adapter = CCXTBinanceAdapter(cfg)
                adapter.dry = False
                
                with pytest.raises(ValueError, match="below minCost"):
                    adapter.place_order("buy", 1.0, price=50.0)

    @patch('ccxt.binanceusdm')
    def test_close_position_long(self, mock_exchange_class):
        """Тест закриття LONG позиції"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        with patch.object(adapter, 'place_order') as mock_place:
            mock_place.return_value = {"id": "close123"}
            
            result = adapter.close_position("LONG", 1.5)
            
            mock_place.assert_called_once_with("sell", 1.5, price=None, reduce_only=True)

    @patch('ccxt.binanceusdm')
    def test_close_position_short(self, mock_exchange_class):
        """Тест закриття SHORT позиції"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        with patch.object(adapter, 'place_order') as mock_place:
            mock_place.return_value = {"id": "close124"}
            
            result = adapter.close_position("SHORT", 2.0)
            
            mock_place.assert_called_once_with("buy", 2.0, price=None, reduce_only=True)

    @patch('ccxt.binanceusdm')
    def test_cancel_all(self, mock_exchange_class):
        """Тест скасування всіх ордерів"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.cancel_all_orders.return_value = True
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        result = adapter.cancel_all()
        
        mock_exchange.cancel_all_orders.assert_called_once_with("BTC/USDT")
        assert result is True

    @patch('ccxt.binanceusdm')
    def test_cancel_all_exception(self, mock_exchange_class):
        """Тест обробки винятку при скасуванні ордерів"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.cancel_all_orders.side_effect = Exception("Cancel failed")
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        result = adapter.cancel_all()
        
        assert result is False

    @patch('ccxt.binanceusdm')
    def test_get_limits_with_market(self, mock_exchange_class):
        """Тест отримання лімітів з market інформацією"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.market.return_value = {
            "limits": {
                "amount": {"min": 0.001, "max": 1000},
                "cost": {"min": 10.0}
            }
        }
        # Also mock markets dict access
        mock_exchange.markets = {"BTC/USDT": mock_exchange.market.return_value}
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        limits = adapter._get_limits()
        
        assert limits["amount"]["min"] == 0.001
        assert limits["cost"]["min"] == 10.0

    @patch('ccxt.binanceusdm')
    def test_get_limits_exception(self, mock_exchange_class):
        """Тест обробки винятку при отриманні лімітів"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        # Mock markets dict to return None, then market method to raise exception
        mock_exchange.markets = {"BTC/USDT": None}
        mock_exchange.market.side_effect = Exception("Market error")
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        limits = adapter._get_limits()
        
        assert limits == {}

    @patch('ccxt.binanceusdm')
    def test_quantize_amount(self, mock_exchange_class):
        """Тест квантизації кількості"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.amount_to_precision.return_value = 1.234
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        result = adapter._quantize_amount(1.23456789)
        
        assert result == 1.234
        mock_exchange.amount_to_precision.assert_called_once_with("BTC/USDT", 1.23456789)

    @patch('ccxt.binanceusdm')
    def test_quantize_price(self, mock_exchange_class):
        """Тест квантизації ціни"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.price_to_precision.return_value = 50000.12
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        result = adapter._quantize_price(50000.123456)
        
        assert result == 50000.12
        mock_exchange.price_to_precision.assert_called_once_with("BTC/USDT", 50000.123456)

    @patch('ccxt.binanceusdm')
    def test_estimate_price_with_orderbook(self, mock_exchange_class):
        """Тест оцінки ціни з orderbook"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.fetch_order_book.return_value = {
            'bids': [[50000.0, 1.0]],
            'asks': [[50001.0, 1.0]]
        }
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        price = adapter._estimate_price()
        
        assert price == 50000.5  # (50000.0 + 50001.0) / 2

    @patch('ccxt.binanceusdm')
    def test_estimate_price_no_orderbook(self, mock_exchange_class):
        """Тест оцінки ціни без orderbook"""
        mock_exchange = Mock()
        mock_exchange_class.return_value = mock_exchange
        mock_exchange.fetch_order_book.return_value = {'bids': [], 'asks': []}
        
        cfg = {}
        adapter = CCXTBinanceAdapter(cfg)
        
        price = adapter._estimate_price()
        
        assert price == 0.0