"""
Unit tests for schema_linter.py
Tests YAML schema validation, consistency checks, and CLI functionality.
"""
import json
import tempfile
import pytest
import yaml
from pathlib import Path
from unittest.mock import patch
import sys
import os

# Add tools directory to path for importing schema_linter
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'tools'))

from schema_linter import (
    load_yaml_file, 
    validate_ci_thresholds, 
    validate_hard_meta_consistency,
    validate_threshold_naming,
    CI_THRESHOLDS_SCHEMA
)

def test_load_yaml_file_valid():
    """Test loading valid YAML file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump({"test": "value"}, f)
        f.flush()
        
        result = load_yaml_file(f.name)
        assert result == {"test": "value"}
        
        # Cleanup
        os.unlink(f.name)

def test_load_yaml_file_invalid_syntax():
    """Test loading YAML with syntax errors."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        f.write("invalid: yaml: syntax: [\n")
        f.flush()
        
        with pytest.raises(ValueError, match="Invalid YAML syntax"):
            load_yaml_file(f.name)
        
        # Cleanup
        os.unlink(f.name)

def test_load_yaml_file_not_found():
    """Test loading non-existent file."""
    with pytest.raises(ValueError, match="File not found"):
        load_yaml_file("non_existent_file.yaml")

def test_validate_ci_thresholds_valid():
    """Test schema validation with valid data."""
    valid_data = {
        "thresholds": {
            "alpha_target": 0.1,
            "ctr_min": 0.95
        },
        "meta": {
            "generation_time": "2025-08-16T14:30:00Z",
            "window_size": 7
        }
    }
    
    is_valid, errors = validate_ci_thresholds(valid_data)
    assert is_valid
    assert errors == []

def test_validate_ci_thresholds_missing_required():
    """Test schema validation with missing required fields."""
    invalid_data = {
        "thresholds": {
            "alpha_target": 0.1
        }
        # Missing 'meta' section
    }
    
    is_valid, errors = validate_ci_thresholds(invalid_data)
    assert not is_valid
    assert len(errors) > 0
    assert "'meta' is a required property" in str(errors[0])

def test_validate_ci_thresholds_invalid_types():
    """Test schema validation with invalid data types."""
    invalid_data = {
        "thresholds": {
            "alpha_target": "not_a_number"  # Should be number
        },
        "meta": {
            "generation_time": "2025-08-16T14:30:00Z",
            "window_size": "not_an_integer"  # Should be integer
        }
    }
    
    is_valid, errors = validate_ci_thresholds(invalid_data)
    assert not is_valid
    assert len(errors) > 0

def test_validate_hard_meta_consistency_valid():
    """Test hard_meta consistency validation with valid data."""
    valid_data = {
        "hard_meta": {
            "schema_version": 1,
            "hard_candidate": {
                "dcts_min": True,
                "ctr_min": False
            },
            "reasons": {
                "dcts_min": "stability_ok",
                "ctr_min": "high_variance"
            },
            "dcts_min": {
                "hard_enabled": True,
                "hard_reason": "stability_ok"
            }
        }
    }
    
    errors = validate_hard_meta_consistency(valid_data)
    assert errors == []

def test_validate_hard_meta_consistency_schema_version():
    """Test hard_meta schema version validation."""
    invalid_data = {
        "hard_meta": {
            "schema_version": 2  # Should be 1
        }
    }
    
    errors = validate_hard_meta_consistency(invalid_data)
    assert len(errors) > 0
    assert "schema_version should be 1" in errors[0]

def test_validate_hard_meta_consistency_missing_reason():
    """Test hard_meta consistency when candidate missing reason."""
    invalid_data = {
        "hard_meta": {
            "schema_version": 1,
            "hard_candidate": {
                "dcts_min": True
            },
            "reasons": {}  # Missing reason for dcts_min
        }
    }
    
    errors = validate_hard_meta_consistency(invalid_data)
    assert len(errors) > 0
    assert "missing corresponding reason" in errors[0]

def test_validate_hard_meta_consistency_orphan_reason():
    """Test hard_meta consistency when reason has no candidate."""
    invalid_data = {
        "hard_meta": {
            "schema_version": 1,
            "hard_candidate": {},
            "reasons": {
                "orphan_metric": "some_reason"  # No corresponding candidate
            }
        }
    }
    
    errors = validate_hard_meta_consistency(invalid_data)
    assert len(errors) > 0
    assert "exists but metric not in hard_candidate" in errors[0]

def test_validate_hard_meta_consistency_enabled_not_candidate():
    """Test hard_meta consistency when enabled metric is not candidate."""
    invalid_data = {
        "hard_meta": {
            "schema_version": 1,
            "hard_candidate": {
                "dcts_min": False  # Not a candidate
            },
            "reasons": {
                "dcts_min": "reason"
            },
            "dcts_min": {
                "hard_enabled": True  # But enabled anyway
            }
        }
    }
    
    errors = validate_hard_meta_consistency(invalid_data)
    assert len(errors) > 0
    assert "hard_enabled=true but hard_candidate=false" in errors[0]

def test_validate_threshold_naming_valid():
    """Test threshold naming validation with valid names."""
    valid_data = {
        "thresholds": {
            "alpha_target": 0.1,
            "ctr_min": 0.95,
            "tvf2.dcts": 0.9,
            "_private_threshold": 0.5
        }
    }
    
    errors = validate_threshold_naming(valid_data)
    assert errors == []

def test_validate_threshold_naming_invalid():
    """Test threshold naming validation with invalid names."""
    invalid_data = {
        "thresholds": {
            "2alpha": 0.1,          # Starts with number
            "invalid-name": 0.95,   # Contains hyphen
            "space name": 0.9,      # Contains space
            "special@char": 0.5     # Contains special character
        }
    }
    
    errors = validate_threshold_naming(invalid_data)
    assert len(errors) == 4
    for error in errors:
        assert "Invalid threshold name" in error

def test_cli_main_valid_file():
    """Test CLI main function with valid file.""" 
    valid_data = {
        "thresholds": {"alpha_target": 0.1},
        "meta": {"generation_time": "2025-08-16T14:30:00Z"}
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(valid_data, f)
        f.flush()
        
        # Mock sys.argv for CLI test
        with patch('sys.argv', ['schema_linter.py', f.name]):
            from schema_linter import main
            exit_code = main()
            assert exit_code == 0
        
        # Cleanup
        os.unlink(f.name)

def test_cli_main_invalid_file():
    """Test CLI main function with invalid file."""
    invalid_data = {
        "thresholds": {"alpha_target": "not_a_number"},
        # Missing meta section
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml.dump(invalid_data, f)
        f.flush()
        
        # Mock sys.argv for CLI test
        with patch('sys.argv', ['schema_linter.py', f.name]):
            from schema_linter import main
            exit_code = main()
            assert exit_code == 1
        
        # Cleanup
        os.unlink(f.name)

def test_schema_structure():
    """Test that the CI_THRESHOLDS_SCHEMA is well-formed."""
    # Basic schema structure checks
    assert "type" in CI_THRESHOLDS_SCHEMA
    assert CI_THRESHOLDS_SCHEMA["type"] == "object"
    assert "properties" in CI_THRESHOLDS_SCHEMA
    assert "required" in CI_THRESHOLDS_SCHEMA
    
    # Required fields
    assert "thresholds" in CI_THRESHOLDS_SCHEMA["required"]
    assert "meta" in CI_THRESHOLDS_SCHEMA["required"]
    
    # Properties exist
    properties = CI_THRESHOLDS_SCHEMA["properties"]
    assert "thresholds" in properties
    assert "meta" in properties
    assert "hard_meta" in properties
    assert "metric_meta" in properties
    assert "ratchet_meta" in properties

def test_empty_hard_meta():
    """Test validation with empty hard_meta section."""
    data_with_empty_hard_meta = {
        "thresholds": {"alpha_target": 0.1},
        "meta": {"generation_time": "2025-08-16T14:30:00Z"},
        "hard_meta": {}
    }
    
    # Should pass schema validation
    is_valid, errors = validate_ci_thresholds(data_with_empty_hard_meta)
    assert is_valid
    
    # Should pass consistency checks (empty is valid)
    consistency_errors = validate_hard_meta_consistency(data_with_empty_hard_meta)
    assert consistency_errors == []

def test_pattern_properties_exclusion():
    """Test that reserved fields are excluded from pattern matching."""
    data_with_reserved_fields = {
        "thresholds": {"alpha_target": 0.1},
        "meta": {"generation_time": "2025-08-16T14:30:00Z"},
        "hard_meta": {
            "schema_version": 1,
            "window_n": 42,
            "warn_rate_k": 0.23,
            "p95_p10_delta": 0.15,
            "var_ratio_rb": 0.8,
            "hard_candidate": {},
            "reasons": {},
            "decided_by": "test",
            "timestamp": "2025-08-16T14:30:00Z"
        }
    }
    
    # These reserved fields should not be treated as threshold enablement objects
    is_valid, errors = validate_ci_thresholds(data_with_reserved_fields)
    assert is_valid, f"Validation failed: {errors}"

if __name__ == "__main__":
    pytest.main([__file__, "-v"])