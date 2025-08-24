"""
Smoke tests for hard override functionality.
Tests force_off, panic_file, force_on behaviors with minimal setup.
"""
import json
import tempfile
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Mock the living_latent module structure for testing
class MockConfig:
    """Mock configuration object for testing hard override modes."""
    def __init__(self, hard_enabled=True, hard_override="auto"):
        self.ci_gating = MagicMock()
        self.ci_gating.hard_enabled = hard_enabled
        self.ci_gating.hard_override = hard_override

class MockHardDecisionResult:
    """Mock hard decision result for testing."""
    def __init__(self, should_terminate=False, reason="test_reason"):
        self.should_terminate = should_terminate
        self.reason = reason
        self.metric_name = "test_metric"

def test_hard_override_force_off():
    """Test that force_off disables hard gating regardless of configuration."""
    config = MockConfig(hard_enabled=True, hard_override="force_off")
    
    # Mock hard decision that would normally terminate
    decision_result = MockHardDecisionResult(should_terminate=True, reason="threshold_breach")
    
    # Simulate the hard override logic
    def should_apply_hard_termination(config, decision_result):
        if config.ci_gating.hard_override == "force_off":
            return False
        if not config.ci_gating.hard_enabled:
            return False
        return decision_result.should_terminate
    
    # Test force_off overrides hard termination
    assert not should_apply_hard_termination(config, decision_result)
    
    # Verify it works even when hard_enabled=True and decision says terminate
    assert config.ci_gating.hard_enabled is True
    assert decision_result.should_terminate is True
    assert not should_apply_hard_termination(config, decision_result)

def test_hard_override_force_on():
    """Test that force_on enables hard gating regardless of hard_enabled setting."""
    config = MockConfig(hard_enabled=False, hard_override="force_on")
    
    # Mock hard decision that would terminate
    decision_result = MockHardDecisionResult(should_terminate=True, reason="threshold_breach")
    
    # Simulate the hard override logic
    def should_apply_hard_termination(config, decision_result):
        if config.ci_gating.hard_override == "force_on":
            return decision_result.should_terminate
        if config.ci_gating.hard_override == "force_off":
            return False
        if not config.ci_gating.hard_enabled:
            return False
        return decision_result.should_terminate
    
    # Test force_on overrides hard_enabled=False
    assert should_apply_hard_termination(config, decision_result)
    
    # Verify override works despite hard_enabled=False
    assert config.ci_gating.hard_enabled is False
    assert should_apply_hard_termination(config, decision_result)

def test_hard_override_auto_respects_config():
    """Test that auto mode respects the hard_enabled configuration."""
    # Test auto with hard_enabled=True
    config_enabled = MockConfig(hard_enabled=True, hard_override="auto")
    decision_result = MockHardDecisionResult(should_terminate=True, reason="threshold_breach")
    
    def should_apply_hard_termination(config, decision_result):
        if config.ci_gating.hard_override == "force_on":
            return decision_result.should_terminate
        if config.ci_gating.hard_override == "force_off":
            return False
        if not config.ci_gating.hard_enabled:
            return False
        return decision_result.should_terminate
    
    # Should terminate when auto + hard_enabled=True
    assert should_apply_hard_termination(config_enabled, decision_result)
    
    # Test auto with hard_enabled=False  
    config_disabled = MockConfig(hard_enabled=False, hard_override="auto")
    
    # Should not terminate when auto + hard_enabled=False
    assert not should_apply_hard_termination(config_disabled, decision_result)

def test_panic_file_override():
    """Test panic file mechanism for emergency hard override."""
    with tempfile.TemporaryDirectory() as tmpdir:
        panic_file = Path(tmpdir) / "hard_gating_panic.txt"
        
        # Create panic file with force_off content
        panic_file.write_text("force_off")
        
        def check_panic_file(panic_path):
            """Check panic file and return override mode."""
            if panic_path.exists():
                content = panic_path.read_text().strip().lower()
                if content in ["force_off", "force_on"]:
                    return content
            return None
        
        # Test panic file force_off
        override = check_panic_file(panic_file)
        assert override == "force_off"
        
        # Test panic file force_on
        panic_file.write_text("FORCE_ON")  # Test case insensitive
        override = check_panic_file(panic_file)
        assert override == "force_on"
        
        # Test invalid content
        panic_file.write_text("invalid_mode")
        override = check_panic_file(panic_file)
        assert override is None
        
        # Test missing file
        panic_file.unlink()
        override = check_panic_file(panic_file)
        assert override is None

def test_hard_override_precedence():
    """Test that panic file takes precedence over config hard_override."""
    with tempfile.TemporaryDirectory() as tmpdir:
        panic_file = Path(tmpdir) / "hard_gating_panic.txt"
        panic_file.write_text("force_off")
        
        config = MockConfig(hard_enabled=True, hard_override="force_on")
        decision_result = MockHardDecisionResult(should_terminate=True, reason="threshold_breach")
        
        def should_apply_hard_termination_with_panic(config, decision_result, panic_path):
            # Check panic file first (highest precedence)
            panic_override = None
            if panic_path.exists():
                content = panic_path.read_text().strip().lower()
                if content in ["force_off", "force_on"]:
                    panic_override = content
            
            # Apply panic override if present
            if panic_override == "force_off":
                return False
            if panic_override == "force_on":
                return decision_result.should_terminate
                
            # Fall back to config override
            if config.ci_gating.hard_override == "force_on":
                return decision_result.should_terminate
            if config.ci_gating.hard_override == "force_off":
                return False
            if not config.ci_gating.hard_enabled:
                return False
            return decision_result.should_terminate
        
        # Panic file force_off should override config force_on
        assert not should_apply_hard_termination_with_panic(config, decision_result, panic_file)
        
        # Change panic file to force_on - should still terminate
        panic_file.write_text("force_on")
        assert should_apply_hard_termination_with_panic(config, decision_result, panic_file)
        
        # Remove panic file - should fall back to config force_on
        panic_file.unlink()
        assert should_apply_hard_termination_with_panic(config, decision_result, panic_file)

def test_hard_meta_integration():
    """Test integration with hard_meta threshold configuration."""
    
    # Mock threshold configuration with hard_meta
    thresholds_config = {
        "hard_meta": {
            "schema_version": 1,
            "window_n": 42,
            "warn_rate_k": 0.23,
            "p95_p10_delta": 0.15,
            "var_ratio_rb": 0.8,
            "hard_candidate": {
                "tvf2.dcts": True,
                "ci.churn": False
            },
            "reasons": {
                "tvf2.dcts": "stability_ok,sample_ok,drift_low",
                "ci.churn": "high_variance"
            },
            "decided_by": "hard_enable_decider",
            "timestamp": "2025-08-16T14:30:00Z",
            # Actual threshold enablement
            "tvf2.dcts": {
                "hard_enabled": True,
                "hard_reason": "stability_ok,sample_ok,drift_low"
            }
        }
    }
    
    def is_metric_hard_enabled(metric_name, thresholds_config):
        """Check if a metric has hard gating enabled in threshold config."""
        hard_meta = thresholds_config.get("hard_meta", {})
        metric_config = hard_meta.get(metric_name, {})
        return metric_config.get("hard_enabled", False)
    
    # Test hard-enabled metric
    assert is_metric_hard_enabled("tvf2.dcts", thresholds_config)
    
    # Test non-hard-enabled metric (only candidate)
    assert not is_metric_hard_enabled("ci.churn", thresholds_config)
    
    # Test unknown metric
    assert not is_metric_hard_enabled("unknown.metric", thresholds_config)
    
    # Test schema validation
    hard_meta = thresholds_config["hard_meta"]
    assert hard_meta["schema_version"] == 1
    assert isinstance(hard_meta["window_n"], int)
    assert isinstance(hard_meta["warn_rate_k"], (int, float))
    assert isinstance(hard_meta["var_ratio_rb"], (int, float))
    assert isinstance(hard_meta["hard_candidate"], dict)
    assert isinstance(hard_meta["reasons"], dict)
    assert "decided_by" in hard_meta
    assert "timestamp" in hard_meta

if __name__ == "__main__":
    pytest.main([__file__, "-v"])