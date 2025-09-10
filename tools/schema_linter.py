#!/usr/bin/env python3
"""
YAML Schema Validator for CI Thresholds Configuration
Validates ci_thresholds.yaml structure and data types using jsonschema.
"""
import argparse
import json
import sys

from jsonschema import ValidationError, validate
import yaml

# Schema definition for ci_thresholds.yaml
CI_THRESHOLDS_SCHEMA = {
    "$schema": "http://json-schema.org/draft-07/schema#",
    "type": "object",
    "required": ["thresholds", "meta"],
    "properties": {
        "thresholds": {
            "type": "object",
            "description": "Scalar threshold limits for CI gating",
            "patternProperties": {
                "^[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                    "type": "number",
                    "description": "Threshold value (numeric)"
                }
            },
            "additionalProperties": False
        },
        "meta": {
            "type": "object",
            "description": "Global derivation metadata",
            "required": ["generation_time"],
            "properties": {
                "generation_time": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}",
                    "description": "ISO timestamp of generation"
                },
                "window_size": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Window size in days"
                },
                "var_ratio_rb": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Variance ratio (robust baseline)"
                },
                "derive_version": {
                    "type": "string",
                    "description": "Version of derive script"
                }
            },
            "additionalProperties": True
        },
        "hard_meta": {
            "type": "object",
            "description": "Hard gating metadata and enablement",
            "properties": {
                "schema_version": {
                    "type": "integer",
                    "enum": [1],
                    "description": "Schema version (currently 1)"
                },
                "window_n": {
                    "type": "integer",
                    "minimum": 1,
                    "description": "Number of summary samples analyzed"
                },
                "warn_rate_k": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Warning rate threshold for candidacy"
                },
                "p95_p10_delta": {
                    "type": "number",
                    "minimum": 0,
                    "description": "P95-P10 delta threshold"
                },
                "var_ratio_rb": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Variance ratio (robust baseline)"
                },
                "hard_candidate": {
                    "type": "object",
                    "description": "Candidacy flags per metric",
                    "patternProperties": {
                        "^[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                            "type": "boolean"
                        }
                    },
                    "additionalProperties": False
                },
                "reasons": {
                    "type": "object",
                    "description": "Reasoning strings per metric",
                    "patternProperties": {
                        "^[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                            "type": "string"
                        }
                    },
                    "additionalProperties": False
                },
                "decided_by": {
                    "type": "string",
                    "description": "Tool/process that generated metadata"
                },
                "timestamp": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}",
                    "description": "ISO timestamp of generation"
                }
            },
            "patternProperties": {
                # Per-threshold hard enablement (e.g. "tvf2.dcts") - exclude reserved fields
                "^(?!schema_version|window_n|warn_rate_k|p95_p10_delta|var_ratio_rb|hard_candidate|reasons|decided_by|timestamp)[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                    "type": "object",
                    "required": ["hard_enabled"],
                    "properties": {
                        "hard_enabled": {
                            "type": "boolean",
                            "description": "Whether hard gating is enabled for this metric"
                        },
                        "hard_reason": {
                            "type": "string",
                            "description": "Reason for hard enablement"
                        }
                    },
                    "additionalProperties": False
                }
            },
            "additionalProperties": False
        },
        "metric_meta": {
            "type": "object",
            "description": "Per-metric statistics and metadata",
            "patternProperties": {
                "^[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                    "type": "object",
                    "properties": {
                        "p95": {"type": "number"},
                        "p10": {"type": "number"},
                        "delta": {"type": "number"},
                        "hard_candidate": {"type": "boolean"},
                        "sample_count": {
                            "type": "integer",
                            "minimum": 0
                        }
                    },
                    "additionalProperties": True
                }
            },
            "additionalProperties": False
        },
        "ratchet_meta": {
            "type": "object",
            "description": "Ratcheting decisions and metadata",
            "properties": {
                "applied_at": {
                    "type": "string",
                    "pattern": "^\\d{4}-\\d{2}-\\d{2}T\\d{2}:\\d{2}:\\d{2}",
                    "description": "ISO timestamp when ratchet was applied"
                },
                "max_step": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "description": "Maximum relative step size used"
                },
                "decisions": {
                    "type": "object",
                    "description": "Per-threshold ratcheting decisions",
                    "patternProperties": {
                        "^[a-zA-Z_][a-zA-Z0-9_\\.]*$": {
                            "type": "string",
                            "enum": ["adopted", "clamped", "unchanged", "skipped_null"],
                            "description": "Ratcheting decision for this threshold"
                        }
                    },
                    "additionalProperties": False
                }
            },
            "additionalProperties": True
        }
    },
    "additionalProperties": False
}

def load_yaml_file(filepath):
    """Load and parse YAML file."""
    try:
        with open(filepath, encoding='utf-8') as f:
            return yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ValueError(f"Invalid YAML syntax: {e}")
    except FileNotFoundError:
        raise ValueError(f"File not found: {filepath}")
    except Exception as e:
        raise ValueError(f"Error reading file: {e}")

def validate_ci_thresholds(data, schema=None):
    """Validate CI thresholds data against schema."""
    if schema is None:
        schema = CI_THRESHOLDS_SCHEMA

    try:
        validate(instance=data, schema=schema)
        return True, []
    except ValidationError as e:
        return False, [str(e)]

def validate_hard_meta_consistency(data):
    """Additional validation for hard_meta consistency."""
    errors = []

    hard_meta = data.get("hard_meta", {})
    if not hard_meta:
        return errors

    # Check schema version
    schema_version = hard_meta.get("schema_version")
    if schema_version != 1:
        errors.append(f"hard_meta.schema_version should be 1, got {schema_version}")

    # Check candidate/reasons consistency
    candidates = hard_meta.get("hard_candidate", {})
    reasons = hard_meta.get("reasons", {})

    # All candidates should have reasons
    for metric in candidates:
        if metric not in reasons:
            errors.append(f"hard_candidate '{metric}' missing corresponding reason")

    # All reasons should have candidates
    for metric in reasons:
        if metric not in candidates:
            errors.append(f"reason for '{metric}' exists but metric not in hard_candidate")

    # Check enabled metrics are candidates
    for key, value in hard_meta.items():
        if isinstance(value, dict) and "hard_enabled" in value:
            if value["hard_enabled"] and not candidates.get(key, False):
                errors.append(f"metric '{key}' has hard_enabled=true but hard_candidate=false")

    return errors

def validate_threshold_naming(data):
    """Validate threshold naming conventions."""
    errors = []
    thresholds = data.get("thresholds", {})

    # Check naming pattern (letters, numbers, dots, underscores)
    import re
    pattern = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_\.]*$')

    for threshold_name in thresholds:
        if not pattern.match(threshold_name):
            errors.append(f"Invalid threshold name '{threshold_name}': must start with letter/underscore, contain only letters/numbers/dots/underscores")

    return errors

def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Validate CI thresholds YAML configuration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python schema_linter.py configs/ci_thresholds.yaml
  python schema_linter.py --schema custom_schema.json configs/ci_thresholds.yaml
  python schema_linter.py --check-consistency configs/ci_thresholds.yaml
        """
    )
    parser.add_argument("file", help="CI thresholds YAML file to validate")
    parser.add_argument("--schema", help="Custom JSON schema file (optional)")
    parser.add_argument("--check-consistency", action="store_true",
                       help="Enable additional consistency checks")
    parser.add_argument("--output-format", choices=["text", "json"], default="text",
                       help="Output format for validation results")
    parser.add_argument("--verbose", "-v", action="store_true",
                       help="Verbose output with detailed validation info")

    args = parser.parse_args()

    # Load custom schema if provided
    schema = CI_THRESHOLDS_SCHEMA
    if args.schema:
        try:
            with open(args.schema) as f:
                schema = json.load(f)
        except Exception as e:
            print(f"Error loading custom schema: {e}", file=sys.stderr)
            return 1

    # Load and validate YAML file
    try:
        data = load_yaml_file(args.file)
    except ValueError as e:
        print(f"Error loading YAML: {e}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Loaded YAML file: {args.file}")
        print(f"Using schema: {'custom' if args.schema else 'built-in'}")

    # Perform schema validation
    is_valid, schema_errors = validate_ci_thresholds(data, schema)

    all_errors = schema_errors.copy()

    # Additional consistency checks
    if args.check_consistency:
        consistency_errors = validate_hard_meta_consistency(data)
        naming_errors = validate_threshold_naming(data)
        all_errors.extend(consistency_errors)
        all_errors.extend(naming_errors)

    # Output results
    if args.output_format == "json":
        result = {
            "file": args.file,
            "valid": len(all_errors) == 0,
            "errors": all_errors,
            "schema_validation": is_valid,
            "consistency_checks": args.check_consistency
        }
        print(json.dumps(result, indent=2))
    else:
        # Text output
        if len(all_errors) == 0:
            print(f"✓ {args.file} is valid")
            if args.verbose:
                print("All validations passed:")
                print("  - Schema validation: PASS")
                if args.check_consistency:
                    print("  - Consistency checks: PASS")
                    print("  - Naming validation: PASS")
        else:
            print(f"✗ {args.file} has {len(all_errors)} error(s):")
            for i, error in enumerate(all_errors, 1):
                print(f"  {i}. {error}")

    # Exit with non-zero code if validation failed
    return 0 if len(all_errors) == 0 else 1

if __name__ == "__main__":
    sys.exit(main())
