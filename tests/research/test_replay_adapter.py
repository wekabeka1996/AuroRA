"""
Unit tests for replay adapter functionality.
Tests the contract for parsing JSON output from tools/replay.
"""

import pytest
import json
import tempfile
import os
from unittest.mock import patch, mock_open, MagicMock

from research.optuna_search import run_replay


class TestReplayAdapter:
    """Test replay simulation adapter functionality."""
    
    def test_run_replay_success(self):
        """Test successful replay execution with valid output."""
        # Mock subprocess.run to simulate successful replay
        mock_metrics = {
            "sharpe": 1.5,
            "return_after_costs": 0.08,
            "risk": {
                "cvar_95": -0.015,
                "max_drawdown": 0.025
            },
            "exec": {
                "latency_p99_ms": 180.0
            },
            "policy": {
                "deny_rate_15m": 0.22
            },
            "calibration": {
                "ece": 0.025
            },
            "tca": {
                "slippage_bps": 1.2,
                "fees_bps": 0.8,
                "adverse_bps": 0.9
            },
            "xai": {
                "top_why": ["momentum", "volume_spike"]
            }
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create expected output file
            out_json = os.path.join(tmpdir, "metrics.json")
            with open(out_json, 'w') as f:
                json.dump(mock_metrics, f)
                
            # Mock subprocess call
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                # Run the function
                result = run_replay(
                    {"test": "config"}, 
                    "test_replay_dir", 
                    tmpdir
                )
                
                # Verify output mapping
                assert result["sharpe"] == 1.5
                assert result["return_adj"] == 0.08
                assert result["cvar95"] == -0.015
                assert result["max_dd"] == 0.025
                assert result["latency_p99"] == 180.0
                assert result["deny_rate"] == 0.22
                assert result["ece"] == 0.025
                assert result["tca_slip_bps"] == 1.2
                assert result["tca_fees_bps"] == 0.8
                assert result["tca_adv_bps"] == 0.9
                assert result["xai_top_why"] == ["momentum", "volume_spike"]
                
    def test_run_replay_missing_fields(self):
        """Test replay output with missing fields (should use defaults)."""
        mock_metrics = {
            "sharpe": 0.8,
            # Missing other fields
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = os.path.join(tmpdir, "metrics.json")
            with open(out_json, 'w') as f:
                json.dump(mock_metrics, f)
                
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                result = run_replay(
                    {"test": "config"}, 
                    "test_replay_dir", 
                    tmpdir
                )
                
                # Verify defaults are used
                assert result["sharpe"] == 0.8
                assert result["return_adj"] == 0.0  # Default
                assert result["cvar95"] == -1.0     # Default (bad)
                assert result["max_dd"] == 1.0      # Default (bad)
                assert result["latency_p99"] == 1e9 # Default (bad)
                assert result["deny_rate"] == 1.0  # Default (bad)
                assert result["ece"] == 1.0        # Default (bad)
                
    def test_run_replay_subprocess_error(self):
        """Test replay failure due to subprocess error."""
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch('subprocess.run') as mock_subprocess:
                # Simulate subprocess failure
                from subprocess import CalledProcessError
                mock_subprocess.side_effect = CalledProcessError(1, 'cmd', stderr="Error message")
                
                with pytest.raises(CalledProcessError):
                    run_replay(
                        {"test": "config"}, 
                        "test_replay_dir", 
                        tmpdir
                    )
                    
    def test_run_replay_creates_profile_file(self):
        """Test that replay creates proper profile YAML file."""
        profile_dict = {
            "sizing": {
                "limits": {"max_notional_usd": 500},
                "kelly_scaler": 0.1
            },
            "execution": {
                "sla": {"max_latency_ms": 200}
            }
        }
        
        mock_metrics = {"sharpe": 0.5}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = os.path.join(tmpdir, "metrics.json")
            with open(out_json, 'w') as f:
                json.dump(mock_metrics, f)
                
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                run_replay(profile_dict, "test_replay_dir", tmpdir)
                
                # Verify profile file was created
                profile_path = os.path.join(tmpdir, "profile_trial.yaml")
                assert os.path.exists(profile_path)
                
                # Verify file contents
                import yaml
                with open(profile_path, 'r') as f:
                    saved_profile = yaml.safe_load(f)
                    
                assert saved_profile["sizing"]["limits"]["max_notional_usd"] == 500
                assert saved_profile["sizing"]["kelly_scaler"] == 0.1
                assert saved_profile["execution"]["sla"]["max_latency_ms"] == 200
                
    def test_run_replay_command_construction(self):
        """Test that the correct subprocess command is constructed."""
        mock_metrics = {"sharpe": 1.0}
        
        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = os.path.join(tmpdir, "metrics.json")
            with open(out_json, 'w') as f:
                json.dump(mock_metrics, f)
                
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                run_replay(
                    {"test": "config"}, 
                    "/path/to/replay_data", 
                    tmpdir
                )
                
                # Verify subprocess was called with correct arguments
                mock_subprocess.assert_called_once()
                call_args = mock_subprocess.call_args[0][0]  # First positional arg
                
                assert call_args[0] == "python"
                assert call_args[1] == "-m"
                assert call_args[2] == "tools.replay"
                assert "--replay-dir" in call_args
                assert "/path/to/replay_data" in call_args
                assert "--profile" in call_args
                assert "--out-json" in call_args
                assert "--strict" in call_args
                assert "false" in call_args


class TestReplayContractCompliance:
    """Test compliance with tools/replay JSON output contract."""
    
    def test_expected_output_structure(self):
        """Test that replay adapter handles expected JSON structure."""
        # This represents the expected output structure from tools/replay
        expected_structure = {
            "sharpe": "float",
            "return_after_costs": "float", 
            "risk": {
                "cvar_95": "float",
                "max_drawdown": "float"
            },
            "exec": {
                "latency_p99_ms": "float"
            },
            "policy": {
                "deny_rate_15m": "float"
            },
            "calibration": {
                "ece": "float"
            },
            "tca": {
                "slippage_bps": "float",
                "fees_bps": "float", 
                "adverse_bps": "float"
            },
            "xai": {
                "top_why": "list"
            }
        }
        
        # Verify each expected field is handled by run_replay
        sample_data = {
            "sharpe": 1.5,
            "return_after_costs": 0.08,
            "risk": {"cvar_95": -0.01, "max_drawdown": 0.02},
            "exec": {"latency_p99_ms": 150.0},
            "policy": {"deny_rate_15m": 0.2},
            "calibration": {"ece": 0.03},
            "tca": {"slippage_bps": 1.0, "fees_bps": 0.5, "adverse_bps": 0.8},
            "xai": {"top_why": ["signal1", "signal2"]}
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            out_json = os.path.join(tmpdir, "metrics.json")
            with open(out_json, 'w') as f:
                json.dump(sample_data, f)
                
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                result = run_replay({}, "test_dir", tmpdir)
                
                # Verify all expected fields are mapped
                required_output_fields = [
                    "sharpe", "return_adj", "tca_slip_bps", "tca_fees_bps", 
                    "tca_adv_bps", "cvar95", "max_dd", "latency_p99", 
                    "deny_rate", "ece", "xai_top_why"
                ]
                
                for field in required_output_fields:
                    assert field in result, f"Missing required field: {field}"


if __name__ == "__main__":
    pytest.main([__file__])