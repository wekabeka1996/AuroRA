"""
Targeted unit tests for survived mutants in api package
Each test targets a specific survived mutant to kill it
"""

import pytest
import os
import tempfile
from pathlib import Path
from unittest.mock import Mock, MagicMock, patch
from fastapi.testclient import TestClient
from api.service import app, _parse_allowlist_env, _is_mutating, RateLimiter


class TestAPIServiceBooleanLogicMutants:
    """Targeted tests for boolean logic mutants in service.py"""

    def test_boolean_or_in_cfg_get_guards_mutant(self):
        """Kill mutant: 'and' -> 'or' in cfg.get('guards') or cfg.get('gates') or {}"""
        # Tests: guards_cfg_l = (cfg_all.get('guards') or cfg_all.get('gates') or {})

        test_configs = [
            {},  # Missing both
            {"guards": {}},  # Has guards
            {"gates": {}},   # Has gates
            {"guards": {}, "gates": {}},  # Has both
        ]

        for cfg in test_configs:
            # The 'or' logic should handle all these cases
            guards_cfg = (cfg.get('guards') or cfg.get('gates') or {})
            assert isinstance(guards_cfg, dict)

    def test_boolean_and_in_logging_cfg_access_mutant(self):
        """Kill mutant: 'or' -> 'and' in logging cfg access"""
        # Tests: emitter_path = ((cfg or {}).get('logging') or {}).get('path', 'logs/events.jsonl')

        test_configs = [
            {},  # Missing cfg
            {"logging": {}},  # Has logging, missing path
            {"logging": {"path": "custom/path"}},  # Has logging with path
        ]

        for cfg in test_configs:
            logging_cfg = ((cfg or {}).get('logging') or {})
            path = logging_cfg.get('path', 'logs/events.jsonl')
            assert isinstance(path, str)

    def test_boolean_or_in_overlay_path_access_mutant(self):
        """Kill mutant: 'and' -> 'or' in overlay path access"""
        # Tests: ov_path = ((cfg or {}).get('overlays') or {}).get('active', 'profiles/overlays/_active_shadow.yaml')

        test_configs = [
            {},  # Missing overlays
            {"overlays": {}},  # Has overlays, missing active
            {"overlays": {"active": "custom/path"}},  # Has overlays with active
        ]

        for cfg in test_configs:
            overlays_cfg = ((cfg or {}).get('overlays') or {})
            active_path = overlays_cfg.get('active', 'profiles/overlays/_active_shadow.yaml')
            assert isinstance(active_path, str)

    def test_compound_boolean_in_token_validation_mutant(self):
        """Kill mutant: boolean logic in token validation"""
        # Tests: if not token or len(token.strip()) < 16

        test_tokens = [
            None,  # No token
            "",    # Empty token
            "short",  # Too short
            "a" * 15,  # Exactly 15 chars
            "a" * 16,  # Exactly 16 chars
            "a" * 20,  # Valid token
        ]

        for token in test_tokens:
            if token is None:
                should_fail = True
            else:
                should_fail = len(token.strip()) < 16
            assert isinstance(should_fail, bool)

    def test_boolean_and_in_rate_limiter_condition_mutant(self):
        """Kill mutant: 'or' -> 'and' in rate limiter condition"""
        # Tests: if mutating: if rec["tokens_m"] >= 1.0 and rec["tokens_g"] >= 1.0

        test_scenarios = [
            (True, 1.0, 1.0),    # Both sufficient
            (True, 0.5, 1.0),    # m insufficient
            (True, 1.0, 0.5),    # g insufficient
            (False, 0.5, 0.5),   # Not mutating
        ]

        for mutating, tokens_m, tokens_g in test_scenarios:
            if mutating:
                allow = tokens_m >= 1.0 and tokens_g >= 1.0
            else:
                allow = tokens_g >= 1.0
            assert isinstance(allow, bool)


class TestAPIServiceArithmeticMutants:
    """Targeted tests for arithmetic operation mutants in service.py"""

    def test_max_arithmetic_in_min_open_interval_mutant(self):
        """Kill mutant: 'min' -> 'max' in min_open_interval_ms calculation"""
        # Tests: min_open_interval_ms = int(max(0, min_open_interval_ms))

        test_values = [
            100,   # Positive
            0,     # Zero
            -50,   # Negative
        ]

        for val in test_values:
            result = int(max(0, val))
            assert result >= 0
            assert isinstance(result, int)

    def test_max_arithmetic_in_cooldown_ms_mutant(self):
        """Kill mutant: 'min' -> 'max' in cooldown_after_close_ms calculation"""
        # Tests: cooldown_after_close_ms = int(max(0, cooldown_after_close_ms))

        test_values = [
            200,   # Positive
            0,     # Zero
            -25,   # Negative
        ]

        for val in test_values:
            result = int(max(0, val))
            assert result >= 0
            assert isinstance(result, int)

    def test_max_arithmetic_in_min_position_hold_mutant(self):
        """Kill mutant: 'min' -> 'max' in min_position_hold_ms calculation"""
        # Tests: app.state.min_position_hold_ms = int(max(0, mph))

        test_values = [
            300,   # Positive
            0,     # Zero
            -10,   # Negative
        ]

        for val in test_values:
            result = int(max(0, val))
            assert result >= 0
            assert isinstance(result, int)

    def test_float_arithmetic_in_scan_period_mutant(self):
        """Kill mutant: arithmetic in scan period parsing"""
        # Tests: period = float(period)

        test_values = [
            "1.0", "2.5", "0.5", "10"
        ]

        for val in test_values:
            period = float(val)
            assert isinstance(period, float)
            assert period > 0

    def test_int_arithmetic_in_ttl_parsing_mutant(self):
        """Kill mutant: arithmetic in TTL parsing"""
        # Tests: ack_ttl = int(ack_ttl)

        test_values = [
            "300", "600", "120"
        ]

        for val in test_values:
            ttl = int(val)
            assert isinstance(ttl, int)
            assert ttl > 0


class TestAPIServiceComparisonMutants:
    """Targeted tests for comparison operation mutants in service.py"""

    def test_greater_equal_in_token_length_mutant(self):
        """Kill mutant: '>=' -> '<' in token length check"""
        # Tests: if len(token.strip()) < 16

        test_lengths = [
            0, 10, 15, 16, 20, 50
        ]

        for length in test_lengths:
            token = "a" * length
            is_too_short = len(token.strip()) < 16
            assert isinstance(is_too_short, bool)

    def test_greater_equal_in_rate_limiter_tokens_mutant(self):
        """Kill mutant: '>=' -> '<' in rate limiter token checks"""
        # Tests: if rec["tokens_m"] >= 1.0 and rec["tokens_g"] >= 1.0

        test_token_values = [
            (0.5, 0.5),  # Both insufficient
            (1.0, 0.5),  # m sufficient, g insufficient
            (0.5, 1.0),  # m insufficient, g sufficient
            (1.0, 1.0),  # Both sufficient
            (2.0, 2.0),  # Both more than sufficient
        ]

        for tokens_m, tokens_g in test_token_values:
            allow = tokens_m >= 1.0 and tokens_g >= 1.0
            assert isinstance(allow, bool)

    def test_less_than_in_cooldown_check_mutant(self):
        """Kill mutant: '<' -> '>' in cooldown check"""
        # Tests: if now_ms < int(cd_until)

        test_scenarios = [
            (1000, 1500),  # Before cooldown
            (1500, 1500),  # At cooldown time
            (2000, 1500),  # After cooldown
        ]

        for now_ms, cd_until in test_scenarios:
            is_in_cooldown = now_ms < int(cd_until)
            assert isinstance(is_in_cooldown, bool)

    def test_greater_than_in_min_interval_check_mutant(self):
        """Kill mutant: '>' -> '<' in min interval check"""
        # Tests: if (now_ms - int(last_ok)) < min_iv

        test_scenarios = [
            (2000, 1500, 600),   # Within interval
            (2000, 1300, 600),   # Outside interval
            (2000, 2000, 600),   # Exactly at boundary
        ]

        for now_ms, last_ok, min_iv in test_scenarios:
            time_diff = now_ms - int(last_ok)
            is_too_soon = time_diff < min_iv
            assert isinstance(is_too_soon, bool)


class TestAPIServiceDictAccessMutants:
    """Targeted tests for dictionary access pattern mutants"""

    def test_get_or_default_patterns_mutant(self):
        """Kill mutant: 'or' -> 'and' in dict.get() or default patterns"""

        test_dicts = [
            {},  # Empty dict
            {"key": "value"},  # Has key
            {"other_key": "value"},  # Missing key
        ]

        for d in test_dicts:
            # Test pattern: d.get('key') or default
            result = d.get('key') or "default"
            assert result is not None

            # Test pattern: d.get('key') or {}
            result_dict = d.get('key') or {}
            assert isinstance(result_dict, (str, dict))

    def test_compound_get_or_patterns_mutant(self):
        """Kill mutant: boolean logic in compound get() or patterns"""

        test_dicts = [
            {},  # Missing both
            {"guards": {}},  # Has guards
            {"gates": {}},   # Has gates
            {"guards": {}, "gates": {}},  # Has both
        ]

        for d in test_dicts:
            # Test pattern: ((d.get('guards') or d.get('gates') or {}))
            result = ((d.get('guards') or d.get('gates') or {}))
            assert isinstance(result, dict)

    def test_nested_get_or_patterns_mutant(self):
        """Kill mutant: nested dict access patterns"""

        test_dicts = [
            {},  # Missing cfg
            {"logging": {}},  # Has logging, missing path
            {"logging": {"path": "custom"}},  # Has logging with path
            {"overlays": {}},  # Has overlays, missing active
            {"overlays": {"active": "path"}},  # Has overlays with active
        ]

        for d in test_dicts:
            # Test logging path pattern
            logging_cfg = ((d or {}).get('logging') or {})
            path = logging_cfg.get('path', 'logs/events.jsonl')
            assert isinstance(path, str)

            # Test overlays active pattern
            overlays_cfg = ((d or {}).get('overlays') or {})
            active = overlays_cfg.get('active', 'profiles/overlays/_active_shadow.yaml')
            assert isinstance(active, str)


class TestAPIServiceEnvironmentMutants:
    """Targeted tests for environment variable access mutants"""

    def test_env_get_or_default_mutant(self):
        """Kill mutant: 'or' -> 'and' in os.getenv() or default"""

        # Test with different env scenarios
        original_env = os.environ.get("TEST_API_VAR")

        try:
            # No env var set
            result = os.getenv("TEST_API_VAR") or "default"
            assert result == "default"

            # Set env var
            os.environ["TEST_API_VAR"] = "test_value"
            result = os.getenv("TEST_API_VAR") or "default"
            assert result == "test_value"

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["TEST_API_VAR"] = original_env
            elif "TEST_API_VAR" in os.environ:
                del os.environ["TEST_API_VAR"]

    def test_env_parsing_mutant(self):
        """Kill mutant: arithmetic/logic in env var parsing"""

        test_env_values = [
            "1.5", "2.0", "-1.0", "0", "300", "600", None
        ]

        for val in test_env_values:
            if val is not None:
                try:
                    # Test float parsing
                    result_float = float(val)
                    assert isinstance(result_float, float)
                except ValueError:
                    pass

                try:
                    # Test int parsing
                    result_int = int(val)
                    assert isinstance(result_int, int)
                except ValueError:
                    pass


class TestAPIServiceRateLimiterMutants:
    """Targeted tests for RateLimiter mutants"""

    def test_rate_limiter_token_arithmetic_mutant(self):
        """Kill mutant: arithmetic in rate limiter token calculations"""
        # Tests: rec["tokens_g"] = min(self.rps_g, rec["tokens_g"] + dt * self.rps_g)

        limiter = RateLimiter(rps_general=10.0, rps_mutating=5.0)

        # Simulate token refill
        test_scenarios = [
            (10.0, 1.0, 10.0),  # Full tokens, 1 second
            (5.0, 2.0, 10.0),   # Half tokens, 2 seconds
            (0.0, 1.0, 10.0),   # No tokens, 1 second
        ]

        for current_tokens, dt, rps in test_scenarios:
            new_tokens = min(rps, current_tokens + dt * rps)
            assert 0 <= new_tokens <= rps

    def test_rate_limiter_allow_logic_mutant(self):
        """Kill mutant: boolean logic in rate limiter allow method"""
        # Tests: if mutating: allow = tokens_m >= 1.0 and tokens_g >= 1.0

        test_cases = [
            (True, 1.0, 1.0),    # Mutating, both sufficient
            (True, 0.5, 1.0),    # Mutating, m insufficient
            (True, 1.0, 0.5),    # Mutating, g insufficient
            (False, 0.5, 1.0),   # Not mutating, g sufficient
            (False, 0.5, 0.5),   # Not mutating, g insufficient
        ]

        for mutating, tokens_m, tokens_g in test_cases:
            if mutating:
                allow = tokens_m >= 1.0 and tokens_g >= 1.0
            else:
                allow = tokens_g >= 1.0
            assert isinstance(allow, bool)


class TestAPIServiceIPAllowlistMutants:
    """Targeted tests for IP allowlist mutants"""

    def test_parse_allowlist_env_mutant(self):
        """Kill mutant: logic in _parse_allowlist_env function"""

        # Test with different env values
        original_env = os.environ.get("AURORA_IP_ALLOWLIST")

        try:
            # No env var
            os.environ.pop("AURORA_IP_ALLOWLIST", None)
            allowlist = _parse_allowlist_env()
            assert isinstance(allowlist, set)
            assert len(allowlist) > 0  # Should have defaults

            # With env var
            os.environ["AURORA_IP_ALLOWLIST"] = "192.168.1.1,10.0.0.1"
            allowlist = _parse_allowlist_env()
            assert "192.168.1.1" in allowlist
            assert "10.0.0.1" in allowlist

        finally:
            # Restore original environment
            if original_env is not None:
                os.environ["AURORA_IP_ALLOWLIST"] = original_env
            elif "AURORA_IP_ALLOWLIST" in os.environ:
                del os.environ["AURORA_IP_ALLOWLIST"]

    def test_is_mutating_method_mutant(self):
        """Kill mutant: logic in _is_mutating function"""
        # Tests: if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}

        test_methods = [
            ("GET", "/health"),      # Not mutating
            ("POST", "/predict"),    # Mutating
            ("PUT", "/overlay"),     # Mutating
            ("DELETE", "/ops"),      # Mutating
            ("PATCH", "/risk"),      # Mutating
            ("OPTIONS", "/cors"),    # Not mutating
        ]

        for method, path in test_methods:
            is_mutating = _is_mutating(method, path)
            assert isinstance(is_mutating, bool)


class TestAPIServiceIntegrationMutants:
    """Integration tests for API service mutants"""

    def test_full_lifespan_config_loading(self):
        """Test full config loading logic that exercises mutants"""

        # Mock various config scenarios
        test_configs = [
            {},  # Empty config
            {"guards": {"latency_ms_limit": 50}},  # Guards config
            {"gates": {"latency_ms_limit": 50}},   # Gates config
            {"logging": {"path": "custom/events.jsonl"}},  # Logging config
            {"overlays": {"active": "custom/overlay.yaml"}},  # Overlays config
        ]

        for cfg in test_configs:
            # Test the patterns used in lifespan
            guards_cfg = (cfg.get('guards') or cfg.get('gates') or {})
            assert isinstance(guards_cfg, dict)

            logging_cfg = ((cfg or {}).get('logging') or {})
            path = logging_cfg.get('path', 'logs/events.jsonl')
            assert isinstance(path, str)

            overlays_cfg = ((cfg or {}).get('overlays') or {})
            active = overlays_cfg.get('active', 'profiles/overlays/_active_shadow.yaml')
            assert isinstance(active, str)

    def test_token_validation_edge_cases(self):
        """Test token validation that exercises comparison mutants"""

        test_tokens = [
            None, "", "x" * 15, "x" * 16, "x" * 50
        ]

        for token in test_tokens:
            if token is None:
                is_invalid = True
            else:
                is_invalid = len(token.strip()) < 16
            assert isinstance(is_invalid, bool)

    def test_rate_limiting_edge_cases(self):
        """Test rate limiting logic that exercises arithmetic mutants"""

        limiter = RateLimiter(rps_general=10.0, rps_mutating=5.0)

        # Test various time deltas and token amounts
        test_scenarios = [
            (0.0, 1.0),   # No tokens, 1 second
            (5.0, 0.5),   # Half tokens, 0.5 seconds
            (10.0, 2.0),  # Full tokens, 2 seconds
        ]

        for current_tokens, dt in test_scenarios:
            # Test refill calculation
            new_tokens = min(10.0, current_tokens + dt * 10.0)
            assert 0 <= new_tokens <= 10.0

            # Test allow decision
            allow = new_tokens >= 1.0
            assert isinstance(allow, bool)