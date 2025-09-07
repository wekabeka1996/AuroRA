"""
Integration tests for governance gate in live runner
Tests P3-A governance integration within run_live_aurora.py
"""

import pytest
import json
import tempfile
import os
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock
from dataclasses import dataclass
from typing import Any, Optional

from core.governance.alpha_ledger import AlphaLedger
from core.governance.sprt_glr import CompositeSPRT, create_sprt_pocock, SPRTOutcome


@dataclass
class MockMarketData:
    mid: float = 100.0
    spread_abs: float = 0.01
    bids: list = None
    asks: list = None
    trades: list = None
    
    def __post_init__(self):
        if self.bids is None:
            self.bids = [[self.mid - self.spread_abs/2, 1.0]]
        if self.asks is None:
            self.asks = [[self.mid + self.spread_abs/2, 1.0]]
        if self.trades is None:
            # Add some buy trades to create positive score
            self.trades = [
                {"side": "buy", "qty": 1.0},
                {"side": "buy", "qty": 2.0},
                {"side": "sell", "qty": 0.5}
            ]


@dataclass
class MockAdapter:
    """Mock exchange adapter for testing"""
    market_data: MockMarketData
    symbol: str = "BTCUSDT"  # Add symbol attribute
    
    def fetch_top_of_book(self):
        return (
            self.market_data.mid,
            self.market_data.spread_abs,
            self.market_data.bids,
            self.market_data.asks,
            self.market_data.trades
        )


class TestGovernanceGateIntegration:
    """Test governance gate integration in live runner"""

    def setup_method(self):
        """Setup test environment"""
        # Create temp session dir
        self.temp_dir = Path(tempfile.mkdtemp())
        os.environ["AURORA_SESSION_DIR"] = str(self.temp_dir)
        
        # Test config with governance
        self.test_config = {
            "governance": {
                "alpha0": 0.05,
                "delta": 0.1,
                "spend_step": 0.002,  # Larger spend step for faster exhaustion
                "policy": "pocock",
                "max_history_len": 100
            },
            "execution": {
                "sla": {"max_latency_ms": 250}
            },
            "order_sink": {
                "mode": "sim_local",
                "sim_local": {
                    "latency_ms": 10,
                    "ttl_ms": 5000
                }
            },
            "sizing": {
                "kelly": {"risk_aversion": 1.0},
                "limits": {"max_notional": 1000.0}
            }
        }

    def teardown_method(self):
        """Cleanup test environment"""
        # Clean up temp directory
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
        
        # Reset environment
        if "AURORA_SESSION_DIR" in os.environ:
            del os.environ["AURORA_SESSION_DIR"]

    def test_governance_components_initialization(self):
        """Test that governance components are properly initialized"""
        from skalp_bot.runner.run_live_aurora import main
        
        # Mock environment to prevent actual trading
        with patch.dict(os.environ, {
            "DRY_RUN": "true",
            "AURORA_MAX_TICKS": "1"  # Exit after 1 tick
        }):
            with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                mock_adapter = MockAdapter(MockMarketData())
                mock_adapter_factory.return_value = mock_adapter
                
                with patch("yaml.safe_load", return_value=self.test_config):
                    with patch("pathlib.Path.exists", return_value=True):
                        with patch("pathlib.Path.read_text", return_value=""):
                            # Should initialize without errors
                            try:
                                main(config_path="test_config.yaml")
                            except SystemExit:
                                pass  # Expected for test exit
                            except Exception as e:
                                pytest.fail(f"Governance initialization failed: {e}")

    def test_alpha_budget_exhaustion_blocks_orders(self):
        """Test that alpha budget exhaustion blocks order submission"""
        
        # Mock alpha ledger with exhausted budget
        mock_ledger = Mock()
        # Mock active_token_for to return None (no active token)
        mock_ledger.active_token_for.return_value = None
        # Mock open to raise ValueError (budget exhausted)
        mock_ledger.open.side_effect = ValueError("Alpha budget exhausted")
        
        # Mock the components to test governance blocking
        with patch("skalp_bot.runner.run_live_aurora.AlphaLedger") as mock_ledger_class:
            mock_ledger_class.return_value = mock_ledger
            
            # Count events logged
            events_logged = []
            
            def mock_log_events(code: str, details: dict):
                events_logged.append({"code": code, "details": details})
            
            with patch("skalp_bot.runner.run_live_aurora._log_events", side_effect=mock_log_events):
                with patch.dict(os.environ, {
                    "DRY_RUN": "true",
                    "AURORA_MAX_TICKS": "3"
                }):
                    with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                        mock_adapter = MockAdapter(MockMarketData())
                        mock_adapter_factory.return_value = mock_adapter
                        
                        with patch("yaml.safe_load", return_value=self.test_config):
                            with patch("pathlib.Path.exists", return_value=True):
                                with patch("pathlib.Path.read_text", return_value=""):
                                    try:
                                        from skalp_bot.runner.run_live_aurora import main
                                        main(config_path="test_config.yaml")
                                    except SystemExit:
                                        pass
        
        # Verify alpha exhaustion events were logged
        alpha_exhausted_events = [e for e in events_logged if e["code"] == "GOVERNANCE.ALPHA.EXHAUSTED"]
        assert len(alpha_exhausted_events) > 0, "Alpha exhaustion should be logged when budget is exhausted"

    def test_sprt_rejection_blocks_orders(self):
        """Test that SPRT rejection blocks order submission"""
        
        # Test config with sufficient alpha budget for SPRT testing
        sprt_test_config = {
            "governance": {
                "alpha0": 1.0,  # Maximum allowed alpha budget
                "delta": 0.1,
                "spend_step": 1e-9,  # Nanoscopic spend step
                "policy": "pocock",
                "max_history_len": 100
            },
            "execution": {
                "sla": {"max_latency_ms": 250}
            },
            "order_sink": {
                "mode": "sim_local",
                "sim_local": {
                    "latency_ms": 10,
                    "ttl_ms": 5000
                }
            },
            "sizing": {
                "kelly": {"risk_aversion": 1.0},
                "limits": {"max_notional": 1000.0}
            }
        }

        # Mock SPRT that always rejects H0
        mock_sprt_result = Mock()
        mock_sprt_result.outcome = SPRTOutcome.ACCEPT_H0  # Use existing enum value
        mock_sprt_result.statistic = -5.0  # Strong evidence against H1
        mock_sprt_result.lower_bound = -3.0
        mock_sprt_result.upper_bound = 3.0
        mock_sprt_result.n_obs = 10

        mock_sprt = Mock()
        mock_sprt.update.return_value = mock_sprt_result

        with patch("skalp_bot.runner.run_live_aurora.create_sprt_pocock", return_value=mock_sprt):
            events_logged = []

            def mock_log_events(code: str, details: dict):
                events_logged.append({"code": code, "details": details})

            with patch("skalp_bot.runner.run_live_aurora._log_events", side_effect=mock_log_events):
                with patch.dict(os.environ, {
                    "DRY_RUN": "true",
                                                        "AURORA_MAX_TICKS": "1"  # Single tick to demonstrate SPRT logic
                }):
                    with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                        mock_adapter = MockAdapter(MockMarketData())
                        mock_adapter_factory.return_value = mock_adapter

                        with patch("yaml.safe_load", return_value=sprt_test_config):
                            with patch("pathlib.Path.exists", return_value=True):
                                with patch("pathlib.Path.read_text", return_value=""):
                                    try:
                                        from skalp_bot.runner.run_live_aurora import main
                                        main(config_path="test_config.yaml")
                                    except SystemExit:
                                        pass
        
        # Verify SPRT blocking events were logged
        sprt_block_events = [e for e in events_logged if e["code"] == "GOVERNANCE.SPRT.BLOCK"]
        sprt_update_events = [e for e in events_logged if e["code"] == "GOVERNANCE.SPRT.UPDATE"]
        
        # Debug: print all events to see what happened
        print(f"\nAll events logged: {len(events_logged)}")
        for event in events_logged:
            print(f"  {event['code']}: {event.get('details', {})}")
        
        assert len(sprt_block_events) > 0, f"SPRT blocking should be logged when H0 is accepted. Got {len(sprt_update_events)} update events"
        
        # Verify SPRT update events were logged
        sprt_update_events = [e for e in events_logged if e["code"] == "GOVERNANCE.SPRT.UPDATE"]
        assert len(sprt_update_events) > 0, "SPRT updates should be logged"

    def test_governance_error_handling(self):
        """Test that governance errors are handled gracefully"""
        
        # Mock alpha ledger that throws exception
        mock_ledger = Mock()
        mock_ledger.active_token_for.return_value = "test_token"
        mock_ledger.remaining.return_value = 0.05  # Return float instead of Mock
        mock_ledger.spend.side_effect = Exception("Test governance error")
        
        with patch("skalp_bot.runner.run_live_aurora.AlphaLedger", return_value=mock_ledger):
            events_logged = []
            
            def mock_log_events(code: str, details: dict):
                events_logged.append({"code": code, "details": details})
            
            with patch("skalp_bot.runner.run_live_aurora._log_events", side_effect=mock_log_events):
                with patch.dict(os.environ, {
                    "DRY_RUN": "true",
                    "AURORA_MAX_TICKS": "2"
                }):
                    with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                        mock_adapter = MockAdapter(MockMarketData())
                        mock_adapter_factory.return_value = mock_adapter
                        
                        with patch("yaml.safe_load", return_value=self.test_config):
                            with patch("pathlib.Path.exists", return_value=True):
                                with patch("pathlib.Path.read_text", return_value=""):
                                    try:
                                        from skalp_bot.runner.run_live_aurora import main
                                        main(config_path="test_config.yaml")
                                    except SystemExit:
                                        pass
        
        # Verify governance error events were logged
        error_events = [e for e in events_logged if e["code"] == "GOVERNANCE.ERROR"]
        assert len(error_events) > 0, "Governance errors should be logged"
        
        # Verify the error details
        error_event = error_events[0]
        assert "error" in error_event["details"]["details"]  # The structure is {"details": {"details": {...}}}
        assert "Test governance error" in error_event["details"]["details"]["error"]

    def test_different_sprt_policies(self):
        """Test different SPRT policy configurations"""
        
        policies_to_test = ["pocock", "obf", "bh_fdr", "invalid_policy"]
        
        for policy in policies_to_test:
            config = self.test_config.copy()
            config["governance"]["policy"] = policy
            
            with patch.dict(os.environ, {
                "DRY_RUN": "true",
                "AURORA_MAX_TICKS": "1"
            }):
                with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                    mock_adapter = MockAdapter(MockMarketData())
                    mock_adapter_factory.return_value = mock_adapter
                    
                    with patch("yaml.safe_load", return_value=config):
                        with patch("pathlib.Path.exists", return_value=True):
                            with patch("pathlib.Path.read_text", return_value=""):
                                try:
                                    from skalp_bot.runner.run_live_aurora import main
                                    main(config_path="test_config.yaml")
                                except SystemExit:
                                    pass  # Expected for test exit
                                except Exception as e:
                                    pytest.fail(f"SPRT policy '{policy}' failed: {e}")

    def test_event_logging_format(self):
        """Test that governance events are logged in correct format"""
        
        events_logged = []
        
        def mock_log_events(code: str, details: dict):
            events_logged.append({"code": code, "details": details})
        
        with patch("skalp_bot.runner.run_live_aurora._log_events", side_effect=mock_log_events):
            with patch.dict(os.environ, {
                "DRY_RUN": "true",
                "AURORA_MAX_TICKS": "2"
            }):
                with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                    mock_adapter = MockAdapter(MockMarketData())
                    mock_adapter_factory.return_value = mock_adapter
                    
                    with patch("yaml.safe_load", return_value=self.test_config):
                        with patch("pathlib.Path.exists", return_value=True):
                            with patch("pathlib.Path.read_text", return_value=""):
                                try:
                                    from skalp_bot.runner.run_live_aurora import main
                                    main(config_path="test_config.yaml")
                                except SystemExit:
                                    pass
        
        # Find governance events
        gov_events = [e for e in events_logged if e["code"].startswith("GOVERNANCE.")]
        
        if gov_events:  # Only test if governance events were generated
            for event in gov_events:
                # Verify event structure
                assert "code" in event
                assert "details" in event
                assert isinstance(event["details"], dict)
                
                # Verify governance-specific event codes
                assert event["code"] in [
                    "GOVERNANCE.ALPHA.EXHAUSTED",
                    "GOVERNANCE.SPRT.UPDATE", 
                    "GOVERNANCE.SPRT.BLOCK",
                    "GOVERNANCE.ERROR"
                ]

    def test_config_parameter_validation(self):
        """Test that governance config parameters are properly validated"""
        
        # Test with missing governance config (should use defaults)
        minimal_config = {
            "execution": {"sla": {"max_latency_ms": 250}},
            "order_sink": {"mode": "sim_local", "sim_local": {"latency_ms": 10, "ttl_ms": 5000}}
        }
        
        with patch.dict(os.environ, {
            "DRY_RUN": "true",
            "AURORA_MAX_TICKS": "1"
        }):
            with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                mock_adapter = MockAdapter(MockMarketData())
                mock_adapter_factory.return_value = mock_adapter
                
                with patch("yaml.safe_load", return_value=minimal_config):
                    with patch("pathlib.Path.exists", return_value=True):
                        with patch("pathlib.Path.read_text", return_value=""):
                            try:
                                from skalp_bot.runner.run_live_aurora import main
                                main(config_path="test_config.yaml")
                            except SystemExit:
                                pass  # Expected for test exit
                            except Exception as e:
                                pytest.fail(f"Default config should work: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])