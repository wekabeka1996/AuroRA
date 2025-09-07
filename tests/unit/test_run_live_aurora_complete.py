"""
Повне тестування run_live_aurora.py з 100% покриттям
"""
import os
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from skalp_bot.runner.run_live_aurora import (
    _session_dir, _log_events, _log_order, create_adapter, 
    _compute_enr, main, _features_hash
)


class TestRunLiveAuroraComplete:
    """Повне тестування run_live_aurora.py для досягнення 100% покриття"""

    def test_session_dir_default(self):
        """Тест дефолтної директорії сесії"""
        with patch.dict(os.environ, {}, clear=True):
            if 'AURORA_SESSION_DIR' in os.environ:
                del os.environ['AURORA_SESSION_DIR']
            path = _session_dir()
            assert path.name == "logs"

    def test_session_dir_custom(self):
        """Тест кастомної директорії сесії"""
        import os
        with patch.dict(os.environ, {'AURORA_SESSION_DIR': '/custom/logs'}):
            path = _session_dir()
            # Використовуємо os.path.normpath для кросплатформності
            expected = os.path.normpath("/custom/logs")
            assert str(path) == expected

    def test_session_dir_creates_directory(self):
        """Тест що директорія створюється"""
        with tempfile.TemporaryDirectory() as tmpdir:
            custom_dir = Path(tmpdir) / "test_logs"
            with patch.dict(os.environ, {'AURORA_SESSION_DIR': str(custom_dir)}):
                path = _session_dir()
                assert path.exists()
                assert path.is_dir()

    @patch('skalp_bot.runner.run_live_aurora._get_events_writer')
    def test_log_events_success(self, mock_writer_func):
        """Тест успішного логування подій"""
        mock_writer = Mock()
        mock_writer_func.return_value = mock_writer

        _log_events("TEST.EVENT", {"test": "data"})

        mock_writer.write_event.assert_called_once()
        written_data = mock_writer.write_event.call_args[0][1]  # Get the second argument (rec)
        assert written_data["event_code"] == "TEST.EVENT"
        assert written_data["test"] == "data"

    @patch('skalp_bot.runner.run_live_aurora._get_events_writer')
    def test_log_events_exception_handling(self, mock_writer_func):
        """Тест обробки винятків при логуванні"""
        mock_writer = Mock()
        mock_writer.write.side_effect = Exception("Write failed")
        mock_writer_func.return_value = mock_writer
        
        # Не повинно кидати виняток
        _log_events("TEST.EVENT", {"test": "data"})

    def test_log_order_without_order_loggers(self):
        """Тест логування ордера без ORDER_LOGGERS"""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {'AURORA_SESSION_DIR': tmpdir}):
                # Забезпечуємо що _ORDER_LOGGERS = None
                import skalp_bot.runner.run_live_aurora as runner_module
                original_loggers = runner_module._ORDER_LOGGERS
                runner_module._ORDER_LOGGERS = None
                
                try:
                    _log_order("success", action="test", order_id="123")
                    
                    # Перевіряємо що файл створився
                    success_file = Path(tmpdir) / "orders_success.jsonl"
                    assert success_file.exists()
                    
                    with open(success_file) as f:
                        data = json.loads(f.read().strip())
                        assert data["action"] == "test"
                        assert data["order_id"] == "123"
                finally:
                    runner_module._ORDER_LOGGERS = original_loggers

    def test_log_order_with_order_loggers(self):
        """Тест логування ордера з ORDER_LOGGERS"""
        mock_loggers = Mock()
        
        import skalp_bot.runner.run_live_aurora as runner_module
        original_loggers = runner_module._ORDER_LOGGERS
        runner_module._ORDER_LOGGERS = mock_loggers
        
        try:
            _log_order("success", action="test", order_id="456")
            mock_loggers.log_success.assert_called_once_with(action="test", order_id="456")
            
            _log_order("failed", reason="error", order_id="789")
            mock_loggers.log_failed.assert_called_once_with(reason="error", order_id="789")
            
            _log_order("denied", deny_reason="risk", order_id="101")
            mock_loggers.log_denied.assert_called_once_with(deny_reason="risk", order_id="101")
        finally:
            runner_module._ORDER_LOGGERS = original_loggers

    def test_log_order_write_failure(self):
        """Тест обробки помилки запису файлу"""
        with patch('builtins.open', side_effect=PermissionError("Access denied")):
            with patch('builtins.print') as mock_print:
                import skalp_bot.runner.run_live_aurora as runner_module
                original_loggers = runner_module._ORDER_LOGGERS
                runner_module._ORDER_LOGGERS = None
                
                try:
                    _log_order("success", action="test")
                    # Повинен надрукувати помилку
                    mock_print.assert_called()
                finally:
                    runner_module._ORDER_LOGGERS = original_loggers

    @patch('skalp_bot.runner.run_live_aurora.SimAdapter')
    def test_create_adapter_sim(self, mock_adapter_class):
        """Тест створення симуляційного адаптера"""
        mock_adapter = Mock()
        mock_adapter_class.return_value = mock_adapter
        
        cfg = {"order_sink": {"mode": "sim_local"}, "symbol": "ETHUSDT"}
        adapter = create_adapter(cfg)
        
        mock_adapter_class.assert_called_once_with(cfg)
        assert adapter == mock_adapter

    def test_compute_enr_allow(self):
        """Тест обчислення ENR що дозволяє торгівлю"""
        cfg = {
            "governance": {
                "expected_net_reward_threshold_bps": -50.0
            }
        }
        
        from skalp_bot.runner.run_live_aurora import Fees
        fees = Fees(maker_fee_bps=0.0, taker_fee_bps=8.0)
        
        result = _compute_enr(cfg, edge_before_bps=100.0, spread_bps=2.0, route='taker', fees=fees)
        
        assert result['outcome'] == 'allow'
        assert result['expected_pnl_proxy_bps'] > -50.0

    def test_compute_enr_deny(self):
        """Тест обчислення ENR що забороняє торгівлю"""
        cfg = {
            "governance": {
                "expected_net_reward_threshold_bps": 50.0
            }
        }
        
        from skalp_bot.runner.run_live_aurora import Fees
        fees = Fees(maker_fee_bps=0.0, taker_fee_bps=8.0)
        
        result = _compute_enr(cfg, edge_before_bps=10.0, spread_bps=20.0, route='taker', fees=fees)
        
        assert result['outcome'] == 'deny'
        assert result['expected_pnl_proxy_bps'] < 50.0

    def test_compute_enr_maker_route(self):
        """Тест обчислення ENR для maker маршруту"""
        cfg = {
            "governance": {
                "expected_net_reward_threshold_bps": 0.0
            }
        }
        
        from skalp_bot.runner.run_live_aurora import Fees
        fees = Fees(maker_fee_bps=0.0, taker_fee_bps=8.0)
        
        result = _compute_enr(cfg, edge_before_bps=50.0, spread_bps=5.0, route='maker', fees=fees)
        
        # Maker повинен мати кращий результат через відсутність комісії та ефект спреду
        assert result['outcome'] == 'allow'

    def test_features_hash(self):
        """Тест хешування фіч"""
        hash1 = _features_hash(0.1, 0.2, 3.0)
        hash2 = _features_hash(0.1, 0.2, 3.0)
        hash3 = _features_hash(0.2, 0.1, 3.0)
        
        assert hash1 == hash2  # Однакові значення
        assert hash1 != hash3  # Різні значення

    @patch('yaml.safe_load')
    @patch('skalp_bot.runner.run_live_aurora.Path')
    def test_main_config_loading(self, mock_path_class, mock_yaml_safe_load):
        """Тест завантаження конфігурації в main"""
        mock_path = Mock()
        mock_path.read_text.return_value = '{"test": "config"}'
        mock_path.__truediv__ = Mock(return_value=Mock())  # Mock the / operator
        mock_path_class.return_value = mock_path
        mock_yaml_safe_load.return_value = {"test": "config"}
        
        with patch.dict(os.environ, {'AURORA_MAX_TICKS': '1'}):
            with patch('skalp_bot.runner.run_live_aurora.create_adapter') as mock_create_adapter:
                mock_adapter = Mock()
                mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [], [], [])
                mock_create_adapter.return_value = mock_adapter
                
                with patch('skalp_bot.runner.run_live_aurora.AuroraGate') as mock_gate:
                    mock_gate_instance = Mock()
                    mock_gate_instance.check.return_value = {"allow": False, "reason": "TEST_DENY"}
                    mock_gate.return_value = mock_gate_instance
                    
                    with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                        main("test_config.yaml")

    @patch('skalp_bot.runner.run_live_aurora.create_adapter')
    def test_main_early_exit_conditions(self, mock_create_adapter):
        """Тест ранніх умов виходу в main"""
        mock_adapter = Mock()
        mock_adapter.symbol = "BTCUSDT"
        mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [(99.99, 1.0)], [(100.01, 1.0)], [])
        mock_create_adapter.return_value = mock_adapter
        
        with patch.dict(os.environ, {'AURORA_MAX_TICKS': '2'}):
            with patch('skalp_bot.runner.run_live_aurora.AuroraGate') as mock_gate:
                mock_gate_instance = Mock()
                mock_gate_instance.check.return_value = {"allow": False, "reason": "EARLY_DENY"}
                mock_gate.return_value = mock_gate_instance
                
                with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                    with patch('skalp_bot.runner.run_live_aurora._log_events'):
                        with patch('skalp_bot.runner.run_live_aurora._log_order'):
                            # Мокаємо функції що можуть викликати помилки
                            with patch('skalp_bot.runner.run_live_aurora.obi_from_l5', return_value=0.1):
                                with patch('skalp_bot.runner.run_live_aurora.tfi_from_trades', return_value=0.2):
                                    with patch('skalp_bot.runner.run_live_aurora.compute_alpha_score', return_value=0.3):
                                        main(None)

    @patch('skalp_bot.runner.run_live_aurora.create_adapter')
    def test_main_acceptance_mode(self, mock_create_adapter):
        """Тест acceptance режиму"""
        mock_adapter = Mock()
        mock_adapter.symbol = "BTCUSDT"
        mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [(99.99, 1.0)], [(100.01, 1.0)], [])
        mock_create_adapter.return_value = mock_adapter
        
        with patch.dict(os.environ, {
            'AURORA_MAX_TICKS': '1',
            'AURORA_ACCEPTANCE_MODE': 'true',
            'DRY_RUN': 'false'  # This should trigger sys.exit(2)
        }):
            with patch('skalp_bot.runner.run_live_aurora.AuroraGate') as mock_gate:
                mock_gate_instance = Mock()
                mock_gate_instance.check.return_value = {"allow": False, "reason": "NETWORK_ERROR"}
                mock_gate.return_value = mock_gate_instance
                
                with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                    with patch('skalp_bot.runner.run_live_aurora._log_events') as mock_log:
                        with patch('skalp_bot.runner.run_live_aurora.obi_from_l5', return_value=0.1):
                            with patch('skalp_bot.runner.run_live_aurora.tfi_from_trades', return_value=0.2):
                                with patch('skalp_bot.runner.run_live_aurora.compute_alpha_score', return_value=0.3):
                                    with pytest.raises(SystemExit) as exc_info:
                                        main(None)
                                    assert exc_info.value.code == 2

    def test_main_exception_handling(self):
        """Тест обробки винятків в main"""
        with patch('skalp_bot.runner.run_live_aurora.create_adapter', side_effect=Exception("Adapter failed")):
            with patch('builtins.print') as mock_print:
                with pytest.raises(Exception) as exc_info:
                    main(None)
                assert "Adapter failed" in str(exc_info.value)

    @patch('skalp_bot.runner.run_live_aurora.create_adapter')
    def test_main_governance_flow(self, mock_create_adapter):
        """Тест governance потоку"""
        mock_adapter = Mock()
        mock_adapter.symbol = "BTCUSDT"
        mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [(99.99, 1.0)], [(100.01, 1.0)], [])
        mock_create_adapter.return_value = mock_adapter
        
        with patch.dict(os.environ, {'AURORA_MAX_TICKS': '1'}):
            with patch('skalp_bot.runner.run_live_aurora.AuroraGate') as mock_gate:
                mock_gate_instance = Mock()
                mock_gate_instance.check.return_value = {"allow": True}
                mock_gate.return_value = mock_gate_instance
                
                with patch('skalp_bot.runner.run_live_aurora.AlphaLedger') as mock_ledger_class:
                    mock_ledger = Mock()
                    mock_ledger.active_token_for.return_value = "test_token"
                    mock_ledger.remaining.return_value = 0.1
                    mock_ledger_class.return_value = mock_ledger
                    
                    with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                        with patch('skalp_bot.runner.run_live_aurora.obi_from_l5', return_value=0.1):
                            with patch('skalp_bot.runner.run_live_aurora.tfi_from_trades', return_value=0.2):
                                with patch('skalp_bot.runner.run_live_aurora.compute_alpha_score', return_value=0.8):
                                    main(None)

    def test_main_testnet_bypass_logic(self):
        """Тест логіки bypass для testnet"""
        with patch.dict(os.environ, {
            'BINANCE_ENV': 'testnet',
            'AURORA_MAX_TICKS': '1'
        }):
            with patch('skalp_bot.runner.run_live_aurora.create_adapter') as mock_create_adapter:
                mock_adapter = Mock()
                mock_adapter.symbol = "BTCUSDT"
                mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [], [], [])
                mock_create_adapter.return_value = mock_adapter
                
                with patch('builtins.print') as mock_print:
                    with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                        main(None)
                        
                        # Повинен надрукувати повідомлення про очищення state
                        print_calls = [str(call) for call in mock_print.call_args_list]
                        assert any("State принудово очищено" in call for call in print_calls)

    @patch('skalp_bot.runner.run_live_aurora.create_adapter')  
    def test_main_order_placement_flow(self, mock_create_adapter):
        """Тест потоку розміщення ордерів"""
        mock_adapter = Mock()
        mock_adapter.symbol = "BTCUSDT"
        mock_adapter.fetch_top_of_book.return_value = (50000.0, 0.01, [(49999.5, 1.0)], [(50000.5, 1.0)], [])
        mock_adapter.place_order.return_value = {"id": "test_order", "status": "closed"}
        mock_create_adapter.return_value = mock_adapter
        
        with patch.dict(os.environ, {'AURORA_MAX_TICKS': '1'}):
            with patch('skalp_bot.runner.run_live_aurora.AuroraGate') as mock_gate:
                mock_gate_instance = Mock()
                mock_gate_instance.check.return_value = {"allow": True}
                mock_gate.return_value = mock_gate_instance
                
                with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                    with patch('skalp_bot.runner.run_live_aurora.obi_from_l5', return_value=0.1):
                        with patch('skalp_bot.runner.run_live_aurora.tfi_from_trades', return_value=0.2):
                            with patch('skalp_bot.runner.run_live_aurora.compute_alpha_score', return_value=0.8):
                                with patch('skalp_bot.runner.run_live_aurora._log_events'):
                                    with patch('skalp_bot.runner.run_live_aurora._log_order'):
                                        main(None)

    def test_integration_with_telemetry(self):
        """Тест інтеграції з телеметрією"""
        with patch('subprocess.run') as mock_subprocess_run:
            mock_process = Mock()
            mock_subprocess_run.return_value = mock_process
            
            with patch.dict(os.environ, {'AURORA_MAX_TICKS': '1'}):
                with patch('skalp_bot.runner.run_live_aurora.create_adapter') as mock_create_adapter:
                    mock_adapter = Mock()
                    mock_adapter.fetch_top_of_book.return_value = (100.0, 0.01, [], [], [])
                    mock_create_adapter.return_value = mock_adapter
                    
                    with patch('skalp_bot.runner.run_live_aurora.time.sleep'):
                        main(None, None, telemetry=True)
                        
                        # Повинен запустити telemetry процес
                        mock_subprocess_run.assert_called()

if __name__ == "__main__":
    pytest.main([__file__])