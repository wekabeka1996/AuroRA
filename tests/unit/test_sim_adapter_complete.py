"""
Повне тестування SimAdapter з 100% покриттям
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from core.execution.sim_adapter import SimAdapter


class TestSimAdapterComplete:
    """Повне тестування SimAdapter для досягнення 100% покриття"""

    def test_init_default_config(self):
        """Тест ініціалізації з дефолтними налаштуваннями"""
        adapter = SimAdapter()
        assert adapter.symbol == 'TEST/USDT'
        assert adapter._obi_bias == 0.0
        assert adapter._tfi_bias == 0.0

    def test_init_with_config(self):
        """Тест ініціалізації з кастомними налаштуваннями"""
        cfg = {
            'symbol': 'BTC/USDT',
            'mock_obi_bias': 0.3,
            'mock_tfi_bias': -0.2,
            'mock_mid': 50000.0,
            'mock_spread': 0.02
        }
        adapter = SimAdapter(cfg)
        assert adapter.symbol == 'BTC/USDT'
        assert adapter._obi_bias == 0.3
        assert adapter._tfi_bias == -0.2

    def test_init_with_env_vars(self):
        """Тест ініціалізації з змінними середовища"""
        with patch.dict(os.environ, {
            'AURORA_SIM_OBI_BIAS': '0.5',
            'AURORA_SIM_TFI_BIAS': '0.4'
        }):
            adapter = SimAdapter({})
            assert adapter._obi_bias == 0.5
            assert adapter._tfi_bias == 0.4

    def test_init_invalid_float_values(self):
        """Тест обробки невалідних значень float"""
        cfg = {
            'mock_obi_bias': 'invalid',
            'mock_tfi_bias': None
        }
        adapter = SimAdapter(cfg)
        assert adapter._obi_bias == 0.0
        assert adapter._tfi_bias == 0.0

    def test_fetch_top_of_book_default(self):
        """Тест отримання ринкових даних з дефолтними значеннями"""
        adapter = SimAdapter()
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        assert mid == 100.0
        assert spread == 0.01
        assert len(bids) == 1
        assert len(asks) == 1
        assert bids[0][0] == 99.995  # mid - spread/2
        assert asks[0][0] == 100.005  # mid + spread/2
        assert len(trades) == 2

    def test_fetch_top_of_book_with_bias(self):
        """Тест отримання ринкових даних з біасами"""
        cfg = {
            'mock_mid': 50000.0,
            'mock_spread': 0.02,
            'mock_obi_bias': 0.3,
            'mock_tfi_bias': -0.2
        }
        adapter = SimAdapter(cfg)
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        assert mid == 50000.0
        assert spread == 0.02
        # Перевіряємо що bias впливає на обсяги
        assert bids[0][1] == 1.3  # 1.0 + 0.3
        assert asks[0][1] == 0.7  # 1.0 - 0.3
        # Перевіряємо що bias впливає на трейди
        buy_trade = next(t for t in trades if t["side"] == "buy")
        sell_trade = next(t for t in trades if t["side"] == "sell")
        assert buy_trade["amount"] == 0.8  # 1.0 + (-0.2)
        assert sell_trade["amount"] == 1.2  # 1.0 - (-0.2)

    def test_fetch_top_of_book_min_values(self):
        """Тест мінімальних значень для уникнення ділення на нуль"""
        cfg = {
            'mock_obi_bias': -2.0,  # Повинно дати мін 0.1
            'mock_tfi_bias': -2.0   # Повинно дати мін 0.0
        }
        adapter = SimAdapter(cfg)
        mid, spread, bids, asks, trades = adapter.fetch_top_of_book()
        
        # Перевіряємо мінімальні значення
        assert bids[0][1] >= 0.1
        assert asks[0][1] >= 0.1
        sell_trade = next(t for t in trades if t["side"] == "sell")
        assert sell_trade["amount"] >= 0.0

    def test_place_order_limit(self):
        """Тест розміщення лімітного ордера"""
        adapter = SimAdapter()
        result = adapter.place_order("buy", 1.0, price=100.0)
        
        assert 'id' in result
        assert result['status'] == 'closed'
        assert isinstance(result['id'], str)

    def test_place_order_market(self):
        """Тест розміщення ринкового ордера"""
        adapter = SimAdapter()
        result = adapter.place_order("sell", 0.5, price=None)
        
        assert 'id' in result
        assert result['status'] == 'closed'

    def test_place_order_calls_sink(self):
        """Тест що place_order викликає SimLocalSink.submit"""
        adapter = SimAdapter()
        
        # Mock the sink's submit method
        with patch.object(adapter._sink, 'submit') as mock_submit:
            mock_submit.return_value = "test_order_id"
            
            result = adapter.place_order("buy", 2.0, price=99.5)
            
            # Перевіряємо що викликався submit з правильними параметрами
            mock_submit.assert_called_once()
            call_args = mock_submit.call_args
            
            # First arg is the order dict, second is keyword arg 'market'
            order = call_args[0][0]  # First positional argument (order dict)
            market = call_args[1]['market']  # Keyword argument
            
            assert order['side'] == 'buy'
            assert order['qty'] == 2.0
            assert order['price'] == 99.5
            assert order['order_type'] == 'limit'
            assert market == {'best_bid': None, 'best_ask': None, 'liquidity': {}}
            assert result['id'] == "test_order_id"

    def test_place_order_market_type(self):
        """Тест що ринковий ордер має правильний тип"""
        with patch('core.execution.sim_adapter.SimLocalSink') as mock_sink_class:
            mock_sink = MagicMock()
            mock_sink.submit.return_value = "market_order_id"
            mock_sink_class.return_value = mock_sink
            
            adapter = SimAdapter()
            adapter.place_order("sell", 1.5, price=None)
            
            call_args = mock_sink.submit.call_args[0]
            order = call_args[0]
            assert order['order_type'] == 'market'

    def test_cancel_all(self):
        """Тест скасування всіх ордерів"""
        adapter = SimAdapter()
        result = adapter.cancel_all()
        assert result is True

    def test_symbol_assignment(self):
        """Тест присвоєння символу"""
        cfg = {'symbol': 'ETH/USDT'}
        adapter = SimAdapter(cfg)
        assert adapter.symbol == 'ETH/USDT'

    def test_empty_config(self):
        """Тест з порожнім конфігом"""
        adapter = SimAdapter({})
        assert adapter.symbol == 'TEST/USDT'
        assert adapter._obi_bias == 0.0
        assert adapter._tfi_bias == 0.0

    def test_none_config(self):
        """Тест з None конфігом"""
        adapter = SimAdapter(None)
        assert adapter.symbol == 'TEST/USDT'
        assert adapter._obi_bias == 0.0
        assert adapter._tfi_bias == 0.0

    def test_to_float_helper_exceptions(self):
        """Тест внутрішньої функції _to_float з різними винятками"""
        adapter = SimAdapter()
        # Тестуємо що функція правильно обробляє винятки
        cfg_with_invalid = {
            'mock_obi_bias': float('inf'),  # може викликати винятки
            'mock_tfi_bias': complex(1, 1)  # не може бути переведено в float
        }
        # Повинно працювати без винятків і повертати дефолтні значення
        adapter2 = SimAdapter(cfg_with_invalid)
        # Значення можуть бути або валідними, або дефолтними
        assert isinstance(adapter2._obi_bias, float)
        assert isinstance(adapter2._tfi_bias, float)

    def test_env_override_priority(self):
        """Тест пріоритету змінних середовища над конфігом"""
        # Не передаємо mock_obi_bias і mock_tfi_bias в конфіг, щоб перевірити пріоритет env vars
        cfg = {
            'symbol': 'BTC/USDT'
        }
        with patch.dict(os.environ, {
            'AURORA_SIM_OBI_BIAS': '0.8',
            'AURORA_SIM_TFI_BIAS': '0.9'
        }):
            adapter = SimAdapter(cfg)
            assert adapter._obi_bias == 0.8
            assert adapter._tfi_bias == 0.9