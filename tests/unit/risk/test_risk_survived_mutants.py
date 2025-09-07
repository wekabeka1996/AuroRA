"""
Targeted unit tests for survived mutants in risk package
Each test targets a specific survived mutant to kill it
"""

import pytest
import os
from risk.manager import RiskManager


class TestRiskManagerConstructorMutants:
    """Test RiskManager constructor to kill mutants in __init__"""

    def test_constructor_cfg_or_mutant(self):
        """Kill mutant: 'or' -> 'and' in manager.py:22 self.cfg = self.load(cfg or {}, dict(os.environ))"""
        # This directly tests the mutant in line 22 of __init__
        # With None config: cfg or {} = {} (original) vs cfg and {} = None (mutant)

        # Original code: cfg or {} -> {} when cfg is None -> should work
        # Mutant code: cfg and {} -> None when cfg is None -> should break
        manager = RiskManager(None)
        assert manager.cfg is not None
        assert manager.cfg.dd_day_pct == 100.0  # Default value

    def test_constructor_with_empty_config_mutant(self):
        """Test RiskManager() with empty config - should trigger line 22"""
        manager = RiskManager({})
        assert manager.cfg is not None
        assert manager.cfg.dd_day_pct == 100.0

    def test_constructor_with_partial_config_mutant(self):
        """Test RiskManager() with partial config - should trigger line 22"""
        config = {"other_section": "value"}
        manager = RiskManager(config)
        assert manager.cfg is not None
        assert manager.cfg.dd_day_pct == 100.0


class TestRiskManagerLoadMethodMutants:
    """Test the load method specifically to kill mutants"""

    def test_load_risk_section_or_mutant(self):
        """Kill mutant: 'or' -> 'and' in manager.py:26 rcfg = (cfg.get('risk') or {})"""
        # This tests the mutant in line 26: rcfg = (cfg.get('risk') or {})

        # Case 1: cfg.get('risk') returns None -> original: {} vs mutant: None
        config_without_risk = {"gates": {"daily_dd_limit_pct": 25.0}}
        result = RiskManager.load(config_without_risk, {})
        # Should use gates value since risk section is missing
        assert result.dd_day_pct == 25.0

        # Case 2: cfg.get('risk') returns dict -> both should work
        config_with_risk = {"risk": {"dd_day_pct": 30.0}}
        result2 = RiskManager.load(config_with_risk, {})
        assert result2.dd_day_pct == 30.0

    def test_load_gates_section_or_mutant(self):
        """Kill mutant: 'or' -> 'and' in manager.py:27 gates = (cfg.get('gates') or {})"""
        # This tests the mutant in line 27: gates = (cfg.get('gates') or {})

        # Case 1: cfg.get('gates') returns None -> original: {} vs mutant: None
        config_without_gates = {"risk": {"dd_day_pct": 30.0}}
        result = RiskManager.load(config_without_gates, {})
        # Should use risk value
        assert result.dd_day_pct == 30.0

        # Case 2: cfg.get('gates') returns dict -> both should work
        config_with_gates = {"gates": {"daily_dd_limit_pct": 25.0}}
        result2 = RiskManager.load(config_with_gates, {})
        assert result2.dd_day_pct == 25.0

    def test_load_dd_precedence_and_mutant(self):
        """Kill mutant: 'and' -> 'or' in manager.py:30 if dd_from_cfg is None and 'daily_dd_limit_pct' in gates:"""
        # This tests line 30: if dd_from_cfg is None and 'daily_dd_limit_pct' in gates:

        # Case 1: dd_from_cfg is None AND key exists in gates -> should use gates value
        # Original: True and True = True -> execute if block
        # Mutant: True or True = True -> execute if block (same behavior)
        config1 = {"gates": {"daily_dd_limit_pct": 25.0}}
        result1 = RiskManager.load(config1, {})
        assert result1.dd_day_pct == 25.0

        # Case 2: dd_from_cfg is not None -> should use dd_from_cfg regardless of gates
        # Original: False and anything = False -> skip if block
        # Mutant: False or anything = anything -> may execute if block incorrectly
        config2 = {"risk": {"dd_day_pct": 30.0}, "gates": {"daily_dd_limit_pct": 25.0}}
        result2 = RiskManager.load(config2, {})
        assert result2.dd_day_pct == 30.0

        # Case 3: dd_from_cfg is None AND key does NOT exist in gates -> should use default
        # Original: True and False = False -> skip if block
        # Mutant: True or False = True -> execute if block incorrectly
        config3 = {"gates": {"other_limit": 50.0}}
        result3 = RiskManager.load(config3, {})
        assert result3.dd_day_pct == 100.0  # Default


class TestRiskManagerEnvOverrideMutants:
    """Test environment variable override logic"""

    def test_env_override_dd_day_pct_mutant(self):
        """Test AURORA_DD_DAY_PCT environment override"""
        original_env = os.environ.get("AURORA_DD_DAY_PCT")

        try:
            os.environ["AURORA_DD_DAY_PCT"] = "45.5"
            config = {"risk": {"dd_day_pct": 30.0}, "gates": {"daily_dd_limit_pct": 25.0}}
            result = RiskManager.load(config, dict(os.environ))
            # Env should override config values
            assert result.dd_day_pct == 45.5

        finally:
            if original_env is not None:
                os.environ["AURORA_DD_DAY_PCT"] = original_env
            elif "AURORA_DD_DAY_PCT" in os.environ:
                del os.environ["AURORA_DD_DAY_PCT"]

    def test_env_override_max_concurrent_mutant(self):
        """Test AURORA_MAX_CONCURRENT environment override"""
        original_env = os.environ.get("AURORA_MAX_CONCURRENT")

        try:
            os.environ["AURORA_MAX_CONCURRENT"] = "15"
            config = {"risk": {"max_concurrent": 10}}
            result = RiskManager.load(config, dict(os.environ))
            assert result.max_concurrent == 15

        finally:
            if original_env is not None:
                os.environ["AURORA_MAX_CONCURRENT"] = original_env
            elif "AURORA_MAX_CONCURRENT" in os.environ:
                del os.environ["AURORA_MAX_CONCURRENT"]

    def test_env_override_size_scale_mutant(self):
        """Test AURORA_SIZE_SCALE environment override"""
        original_env = os.environ.get("AURORA_SIZE_SCALE")

        try:
            os.environ["AURORA_SIZE_SCALE"] = "0.8"
            config = {"risk": {"size_scale": 1.0}}
            result = RiskManager.load(config, dict(os.environ))
            assert result.size_scale == 0.8

        finally:
            if original_env is not None:
                os.environ["AURORA_SIZE_SCALE"] = original_env
            elif "AURORA_SIZE_SCALE" in os.environ:
                del os.environ["AURORA_SIZE_SCALE"]


class TestRiskManagerConfigPrecedenceMutants:
    """Test configuration precedence logic that contains mutants"""

    def test_dd_config_precedence_mutant(self):
        """Test DD config precedence: risk.dd_day_pct > gates.daily_dd_limit_pct > default"""
        # This tests the logic around line 30

        # Case 1: Only gates.daily_dd_limit_pct
        config1 = {"gates": {"daily_dd_limit_pct": 25.0}}
        result1 = RiskManager.load(config1, {})
        assert result1.dd_day_pct == 25.0

        # Case 2: Both risk.dd_day_pct and gates.daily_dd_limit_pct - risk should win
        config2 = {"risk": {"dd_day_pct": 30.0}, "gates": {"daily_dd_limit_pct": 25.0}}
        result2 = RiskManager.load(config2, {})
        assert result2.dd_day_pct == 30.0

        # Case 3: Neither - should use default
        config3 = {"other": "value"}
        result3 = RiskManager.load(config3, {})
        assert result3.dd_day_pct == 100.0

    def test_max_concurrent_precedence_mutant(self):
        """Test max_concurrent precedence: env > config > default"""
        original_env = os.environ.get("AURORA_MAX_CONCURRENT")

        try:
            # Case 1: Only config
            config1 = {"risk": {"max_concurrent": 20}}
            result1 = RiskManager.load(config1, {})
            assert result1.max_concurrent == 20

            # Case 2: Config + env - env should win
            os.environ["AURORA_MAX_CONCURRENT"] = "25"
            result2 = RiskManager.load(config1, dict(os.environ))
            assert result2.max_concurrent == 25

            # Case 3: Neither - default
            result3 = RiskManager.load({}, {})
            assert result3.max_concurrent == 10

        finally:
            if original_env is not None:
                os.environ["AURORA_MAX_CONCURRENT"] = original_env
            elif "AURORA_MAX_CONCURRENT" in os.environ:
                del os.environ["AURORA_MAX_CONCURRENT"]

    def test_size_scale_precedence_mutant(self):
        """Test size_scale precedence: env > config > default"""
        original_env = os.environ.get("AURORA_SIZE_SCALE")

        try:
            # Case 1: Only config
            config1 = {"risk": {"size_scale": 0.9}}
            result1 = RiskManager.load(config1, {})
            assert result1.size_scale == 0.9

            # Case 2: Config + env - env should win
            os.environ["AURORA_SIZE_SCALE"] = "0.7"
            result2 = RiskManager.load(config1, dict(os.environ))
            assert result2.size_scale == 0.7

            # Case 3: Neither - default
            result3 = RiskManager.load({}, {})
            assert result3.size_scale == 1.0

        finally:
            if original_env is not None:
                os.environ["AURORA_SIZE_SCALE"] = original_env
            elif "AURORA_SIZE_SCALE" in os.environ:
                del os.environ["AURORA_SIZE_SCALE"]


class TestRiskManagerSizeScaleClippingMutants:
    """Test size_scale clipping logic"""

    def test_size_scale_clipping_mutant(self):
        """Test size_scale is clipped to [0, 1] range"""
        # Test values below 0
        config1 = {"risk": {"size_scale": -0.5}}
        result1 = RiskManager.load(config1, {})
        assert result1.size_scale == 0.0

        # Test values above 1
        config2 = {"risk": {"size_scale": 1.5}}
        result2 = RiskManager.load(config2, {})
        assert result2.size_scale == 1.0

        # Test values within range
        config3 = {"risk": {"size_scale": 0.5}}
        result3 = RiskManager.load(config3, {})
        assert result3.size_scale == 0.5

    def test_size_scale_clipping_with_env_mutant(self):
        """Test size_scale clipping with environment override"""
        original_env = os.environ.get("AURORA_SIZE_SCALE")

        try:
            # Test env value above 1
            os.environ["AURORA_SIZE_SCALE"] = "1.2"
            result1 = RiskManager.load({}, dict(os.environ))
            assert result1.size_scale == 1.0

            # Test env value below 0
            os.environ["AURORA_SIZE_SCALE"] = "-0.1"
            result2 = RiskManager.load({}, dict(os.environ))
            assert result2.size_scale == 0.0

        finally:
            if original_env is not None:
                os.environ["AURORA_SIZE_SCALE"] = original_env
            elif "AURORA_SIZE_SCALE" in os.environ:
                del os.environ["AURORA_SIZE_SCALE"]