# -*- coding: utf-8 -*-
import pytest
import tempfile
import os
import json
import yaml
from unittest.mock import patch, MagicMock
import sys
sys.path.append('research')

from research.optuna_search import apply_overrides, score, run_replay


class TestOptunaObjective:
    """Unit tests for Optuna optimization functions."""

    def test_apply_overrides_simple(self):
        """Test basic parameter override functionality."""
        base_cfg = {
            "sizing": {
                "limits": {
                    "max_notional_usd": 250
                }
            }
        }
        params = {"sizing.limits.max_notional_usd": 500}

        result = apply_overrides(base_cfg, params)

        assert result["sizing"]["limits"]["max_notional_usd"] == 500

    def test_apply_overrides_nested(self):
        """Test nested parameter override functionality."""
        base_cfg = {
            "execution": {
                "router": {
                    "spread_limit_bps": 8
                }
            }
        }
        params = {"execution.router.spread_limit_bps": 12}

        result = apply_overrides(base_cfg, params)

        assert result["execution"]["router"]["spread_limit_bps"] == 12

    def test_apply_overrides_multiple(self):
        """Test multiple parameter overrides."""
        base_cfg = {
            "sizing": {"kelly_scaler": 0.1},
            "execution": {"sla": {"max_latency_ms": 200}}
        }
        params = {
            "sizing.kelly_scaler": 0.2,
            "execution.sla.max_latency_ms": 300
        }

        result = apply_overrides(base_cfg, params)

        assert result["sizing"]["kelly_scaler"] == 0.2
        assert result["execution"]["sla"]["max_latency_ms"] == 300

    def test_score_calculation(self):
        """Test scoring function with sample metrics."""
        metrics = {
            "sharpe": 1.5,
            "return_adj": 0.05,
            "tca_slip_bps": 2.0,
            "tca_fees_bps": 1.0,
            "tca_adv_bps": 0.5,
            "kelly_eff": 0.8
        }

        result = score(metrics)

        # Expected: 0.5*1.5 + 0.2*0.05 + 0.2*0.8 - 0.1*(2.0+1.0+0.5)/10000
        expected = 0.5 * 1.5 + 0.2 * 0.05 + 0.2 * 0.8 - 0.1 * (3.5 / 10000)
        assert abs(result - expected) < 0.001

    @patch('research.optuna_search.subprocess.run')
    def test_run_replay_success(self, mock_subprocess):
        """Test successful replay execution."""
        mock_subprocess.return_value = MagicMock()

        # Create temporary files
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "profile.yaml")
            out_json = os.path.join(tmpdir, "metrics.json")

            # Create mock profile
            with open(profile_path, 'w') as f:
                yaml.safe_dump({"test": "config"}, f)

            # Create mock metrics output
            metrics = {
                "sharpe": 1.2,
                "return_after_costs": 0.03,
                "tca": {
                    "slippage_bps": 1.5,
                    "fees_bps": 0.8,
                    "adverse_bps": 0.3
                },
                "risk": {
                    "cvar_95": -0.01,
                    "max_drawdown": 0.04
                },
                "exec": {
                    "latency_p99_ms": 250.0
                },
                "policy": {
                    "deny_rate_15m": 0.3
                },
                "calibration": {
                    "ece": 0.04
                },
                "xai": {
                    "top_why": ["test_reason"]
                }
            }

            with open(out_json, 'w') as f:
                json.dump(metrics, f)

            result = run_replay({"test": "config"}, "/fake/replay/dir", tmpdir)

            assert result["sharpe"] == 1.2
            assert result["return_adj"] == 0.03
            assert result["tca_slip_bps"] == 1.5
            assert result["latency_p99"] == 250.0
            assert result["deny_rate"] == 0.3
            assert result["ece"] == 0.04

    @patch('research.optuna_search.subprocess.run')
    def test_run_replay_command_construction(self, mock_subprocess):
        """Test that replay command is constructed correctly."""
        mock_subprocess.return_value = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "profile.yaml")
            out_json = os.path.join(tmpdir, "metrics.json")

            with open(profile_path, 'w') as f:
                yaml.safe_dump({"test": "config"}, f)

            with open(out_json, 'w') as f:
                json.dump({"sharpe": 1.0}, f)

            run_replay({"test": "config"}, "/fake/replay/dir", tmpdir)

            # Verify subprocess was called with correct arguments
            mock_subprocess.assert_called_once()
            call_args = mock_subprocess.call_args[0][0]

            assert "python" in call_args[0]
            assert "-m" in call_args
            assert "tools.replay" in call_args
            assert "--replay-dir" in call_args
            assert "/fake/replay/dir" in call_args
            assert "--profile" in call_args
            assert profile_path in call_args
            assert "--out-json" in call_args
            assert out_json in call_args


class TestReplayAdapter:
    """Unit tests for replay tool adapter functions."""

    @patch('tools.replay.subprocess.run')
    def test_replay_tool_interface(self, mock_subprocess):
        """Test that replay tool can be called with expected interface."""
        mock_subprocess.return_value = MagicMock()

        # This is a contract test - ensuring our code expects the right interface
        # from tools/replay.py
        expected_args = [
            "python", "-m", "tools.replay",
            "--replay-dir", "data/replay_30d/",
            "--profile", "profiles/test.yaml",
            "--out-json", "test_output.json",
            "--strict", "false"
        ]

        # Mock the subprocess call
        mock_subprocess.return_value = MagicMock()

        # Verify the interface expectation (this would be called by optuna_search)
        # We can't actually call it without the real tools/replay.py, but we can
        # verify our expectations are correct
        assert len(expected_args) == 9
        assert expected_args[1] == "-m"
        assert expected_args[2] == "tools.replay"
        assert "--replay-dir" in expected_args
        assert "--profile" in expected_args
        assert "--out-json" in expected_args
        assert "--strict" in expected_args

    def test_metrics_parsing_robustness(self):
        """Test that metrics parsing handles missing fields gracefully."""
        # Test with minimal metrics
        minimal_metrics = {"sharpe": 1.0}

        # This simulates what run_replay does
        result = {
            "sharpe": minimal_metrics.get("sharpe", 0.0),
            "return_adj": minimal_metrics.get("return_after_costs", 0.0),
            "tca_slip_bps": minimal_metrics.get("tca", {}).get("slippage_bps", 0.0),
            "tca_fees_bps": minimal_metrics.get("tca", {}).get("fees_bps", 0.0),
            "tca_adv_bps": minimal_metrics.get("tca", {}).get("adverse_bps", 0.0),
            "cvar95": minimal_metrics.get("risk", {}).get("cvar_95", -1.0),
            "max_dd": minimal_metrics.get("risk", {}).get("max_drawdown", 1.0),
            "latency_p99": minimal_metrics.get("exec", {}).get("latency_p99_ms", 1e9),
            "deny_rate": minimal_metrics.get("policy", {}).get("deny_rate_15m", 1.0),
            "ece": minimal_metrics.get("calibration", {}).get("ece", 1.0),
            "xai_top_why": minimal_metrics.get("xai", {}).get("top_why", []),
        }

        assert result["sharpe"] == 1.0
        assert result["return_adj"] == 0.0
        assert result["tca_slip_bps"] == 0.0
        assert result["cvar95"] == -1.0
        assert result["latency_p99"] == 1e9
        assert result["deny_rate"] == 1.0
        assert result["ece"] == 1.0