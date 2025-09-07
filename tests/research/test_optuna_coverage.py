"""
Additional unit tests to increase coverage for research modules.
"""

import pytest
import json
import tempfile
import os
from unittest.mock import patch, mock_open, MagicMock, call
import yaml
import optuna

from research.optuna_search import (
    apply_overrides, 
    score, 
    run_replay,
    objective,
    main,
    SEARCH_SPACE,
    HARD_LIMITS
)


class TestMainFunction:
    """Test the main entry point function."""
    
    @patch('research.optuna_search.optuna.create_study')
    @patch('research.optuna_search.argparse.ArgumentParser')
    @patch('builtins.open', new_callable=mock_open, read_data='sizing:\\n  limits:\\n    max_notional_usd: 250')
    @patch('yaml.safe_load')
    @patch('yaml.safe_dump')
    @patch('pathlib.Path.mkdir')
    @patch('json.dump')
    def test_main_function_complete_flow(self, mock_json_dump, mock_mkdir, mock_yaml_dump, 
                                       mock_yaml_load, mock_file, mock_parser, mock_create_study):
        """Test complete main function flow."""
        # Setup argument parser mock
        mock_args = MagicMock()
        mock_args.replay_dir = "test_data/"
        mock_args.base_profile = "test_profile.yaml"
        mock_args.n_trials = 5
        mock_args.storage = "sqlite:///test.db"
        mock_args.study = "test_study"
        mock_args.timeout_min = 0
        
        mock_parser_instance = MagicMock()
        mock_parser_instance.parse_args.return_value = mock_args
        mock_parser.return_value = mock_parser_instance
        
        # Setup study mock
        mock_trial = MagicMock()
        mock_trial.value = 1.5
        mock_trial.params = {"test_param": 100}
        mock_trial.user_attrs = {"metrics": {"sharpe": 1.5}}
        
        mock_study = MagicMock()
        mock_study.best_trial = mock_trial
        mock_study.trials = [mock_trial] * 5
        mock_create_study.return_value = mock_study
        
        # Setup YAML loading
        mock_yaml_load.return_value = {"base": "config"}
        
        # Run main function
        main()
        
        # Verify study creation
        mock_create_study.assert_called_once()
        
        # Verify optimization was called
        mock_study.optimize.assert_called_once()
        
        # Verify file operations
        mock_yaml_dump.assert_called()
        mock_json_dump.assert_called()


class TestSearchSpace:
    """Test search space configuration."""
    
    def test_search_space_completeness(self):
        """Test that search space covers all required parameters."""
        required_params = [
            "sizing.limits.max_notional_usd",
            "sizing.limits.leverage_max", 
            "sizing.kelly_scaler",
            "universe.ranking.top_n",
            "execution.router.spread_limit_bps",
            "execution.sla.max_latency_ms",
            "tca.adverse_window_s",
            "reward.ttl_minutes",
            "reward.take_profit_bps",
            "reward.stop_loss_bps",
            "reward.be_break_even_bps"
        ]
        
        for param in required_params:
            assert param in SEARCH_SPACE, f"Missing parameter: {param}"
            
    def test_search_space_ranges(self):
        """Test that search space ranges are reasonable."""
        # Check max_notional_usd range
        low, high, dtype = SEARCH_SPACE["sizing.limits.max_notional_usd"]
        assert low == 50
        assert high == 2000
        assert dtype == int
        
        # Check kelly_scaler range
        low, high, dtype = SEARCH_SPACE["sizing.kelly_scaler"]
        assert low == 0.05
        assert high == 0.5
        assert dtype == float
        
        # Check latency range
        low, high, dtype = SEARCH_SPACE["execution.sla.max_latency_ms"]
        assert low == 50
        assert high == 400
        assert dtype == int


class TestAdvancedScenarios:
    """Test advanced and edge case scenarios."""
    
    def test_apply_overrides_deep_nesting(self):
        """Test applying overrides with very deep nesting."""
        base_cfg = {}
        params = {"level1.level2.level3.level4.value": 42}
        
        result = apply_overrides(base_cfg, params)
        assert result["level1"]["level2"]["level3"]["level4"]["value"] == 42
        
    def test_apply_overrides_overwrites_existing(self):
        """Test that overrides properly overwrite existing values."""
        base_cfg = {"path": {"to": {"value": "old"}}}
        params = {"path.to.value": "new"}
        
        result = apply_overrides(base_cfg, params)
        assert result["path"]["to"]["value"] == "new"
        
    def test_score_extreme_values(self):
        """Test scoring with extreme metric values."""
        metrics = {
            "sharpe": 10.0,         # Very high
            "return_adj": 1.0,      # 100% return
            "kelly_eff": 0.95,      # Near perfect
            "tca_slip_bps": 0.1,    # Very low costs
            "tca_fees_bps": 0.05,
            "tca_adv_bps": 0.05
        }
        
        result = score(metrics)
        assert result > 6.0  # Should be very high score
        
    def test_score_worst_case(self):
        """Test scoring with worst-case metrics."""
        metrics = {
            "sharpe": -2.0,        # Negative Sharpe
            "return_adj": -0.5,    # -50% return
            "kelly_eff": -1.0,     # Negative Kelly (capped to 0)
            "tca_slip_bps": 100.0, # Very high costs
            "tca_fees_bps": 50.0,
            "tca_adv_bps": 75.0
        }
        
        result = score(metrics)
        assert result < -1.0  # Should be very negative score


class TestErrorHandling:
    """Test error handling and edge cases."""
    
    @patch('research.optuna_search.subprocess.run')
    def test_run_replay_subprocess_failure(self, mock_subprocess):
        """Test handling of subprocess failure in run_replay."""
        from subprocess import CalledProcessError
        mock_subprocess.side_effect = CalledProcessError(1, 'cmd', stderr="Replay failed")
        
        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(CalledProcessError):
                run_replay({"test": "config"}, "fake_dir", tmpdir)
                
    @patch('research.optuna_search.run_replay')
    @patch('builtins.open', new_callable=mock_open, read_data='test: config')
    @patch('yaml.safe_load')
    def test_objective_all_constraint_violations(self, mock_yaml_load, mock_file, mock_run_replay):
        """Test objective function with all possible constraint violations."""
        mock_yaml_load.return_value = {"test": "config"}
        
        # Test each constraint violation individually
        constraints = [
            ("cvar95", -0.05, "cvar95 breach"),
            ("max_dd", 0.10, "max_dd breach"),
            ("latency_p99", 500.0, "latency p99 breach"),
            ("deny_rate", 0.50, "deny‑rate breach"),
            ("ece", 0.10, "ECE breach")
        ]
        
        for field, bad_value, expected_message in constraints:
            mock_trial = MagicMock()
            mock_args = MagicMock()
            mock_args.base_profile = "test.yaml"
            mock_args.replay_dir = "test_data/"
            
            # Create metrics with one bad constraint
            metrics = {
                "cvar95": -0.01,      # Good
                "max_dd": 0.03,       # Good
                "latency_p99": 250.0, # Good
                "deny_rate": 0.25,    # Good
                "ece": 0.03           # Good
            }
            metrics[field] = bad_value  # Make this one bad
            
            mock_run_replay.return_value = metrics
            
            with pytest.raises(optuna.TrialPruned, match=expected_message):
                objective(mock_trial, mock_args)


class TestFileOperations:
    """Test file I/O operations."""
    
    def test_run_replay_yaml_encoding(self):
        """Test that YAML files are properly encoded."""
        profile_dict = {
            "unicode_field": "тест",  # Cyrillic text
            "nested": {"value": "العربية"}  # Arabic text
        }
        
        with tempfile.TemporaryDirectory() as tmpdir:
            profile_path = os.path.join(tmpdir, "profile_trial.yaml")
            out_json = os.path.join(tmpdir, "metrics.json")
            
            # Create mock metrics file
            with open(out_json, 'w') as f:
                json.dump({"sharpe": 1.0}, f)
                
            with patch('subprocess.run') as mock_subprocess:
                mock_subprocess.return_value = MagicMock()
                
                run_replay(profile_dict, "test_dir", tmpdir)
                
                # Verify file was created and is readable
                assert os.path.exists(profile_path)
                
                with open(profile_path, 'r', encoding='utf-8') as f:
                    loaded_profile = yaml.safe_load(f)
                    
                assert loaded_profile["unicode_field"] == "тест"
                assert loaded_profile["nested"]["value"] == "العربية"


if __name__ == "__main__":
    pytest.main([__file__])