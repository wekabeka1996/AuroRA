"""
SSOT validation tool for config validation.
"""
import sys
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

# Known top-level configuration keys
SCHEMA = [
    "risk", "execution", "governance", "features", "signal", "calibration",
    "regime", "tca", "sizing", "profile", "universe", "xai", "leadlag",
    "replay", "timescale", "hotreload", "logger", "order_sink", "market_data",
    "orders", "name"
]

# Required top-level keys
REQUIRED_KEYS = ["risk", "execution", "timescale"]


def check_live_mode_invariants(config: Dict[str, Any]) -> List[str]:
    """Check invariants required for live mode operation."""
    issues = []
    
    # Only check live mode invariants if we have market_data or order_sink indicating live mode
    market_data = config.get("market_data", {})
    order_sink = config.get("order_sink", {})
    
    # Check if this looks like a live configuration
    is_live_config = (
        market_data.get("source", "").startswith("live_") or
        "live" in str(order_sink).lower() or
        config.get("orders", {}).get("enabled", False)
    )
    
    if not is_live_config:
        return issues
    
    # Check market_data.source for live mode
    source = market_data.get("source", "")
    if source.startswith("live_") and source != "live_binance":
        issues.append("market_data.source must be 'live_binance' for live operations")
    
    # Check order_sink.mode for live mode
    mode = order_sink.get("mode", "")
    if mode == "net":
        # In live mode, net mode should not be allowed without proper credentials
        issues.append("order_sink.mode 'net' requires live trading credentials")
    
    # Check orders.enabled for live mode
    orders = config.get("orders", {})
    if not orders.get("enabled", False):
        issues.append("orders.enabled must be true for live operations")
    
    return issues


def check_missing_required_keys(config: Dict[str, Any], required_keys: List[str]) -> List[str]:
    """Check for missing required keys."""
    missing = []
    for key in required_keys:
        if key not in config:
            missing.append(key)
    return missing


def _check_unknown_top_level(config: Dict[str, Any], known_keys: List[str]) -> List[str]:
    """Check for unknown top-level keys."""
    unknown = []
    for key in config.keys():
        if key not in known_keys:
            unknown.append(key)
    return unknown


def check_unknown_and_nulls(config: Dict[str, Any]) -> Dict[str, Any]:
    """Check for unknown keys and null values."""
    unknown = _check_unknown_top_level(config, SCHEMA)
    nulls = []
    
    # Check for null/empty values recursively
    def check_nulls_recursive(data: Any, path: str = "") -> None:
        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}" if path else key
                if value is None or (isinstance(value, str) and value.strip() == ""):
                    nulls.append(current_path)
                elif isinstance(value, (dict, list)):
                    check_nulls_recursive(value, current_path)
        elif isinstance(data, list):
            for i, item in enumerate(data):
                current_path = f"{path}[{i}]"
                check_nulls_recursive(item, current_path)
    
    check_nulls_recursive(config)
    
    return {
        "unknown_keys": unknown,
        "null_values": nulls
    }


def validate_config(config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate configuration."""
    errors = []
    warnings = []

    # Check missing required keys first
    missing = check_missing_required_keys(config, REQUIRED_KEYS)
    if missing:
        errors.append(f"Missing required keys: {missing}")

    # Check unknown keys
    unknown = _check_unknown_top_level(config, SCHEMA)
    if unknown:
        errors.append(f"Unknown top-level keys: {unknown}")

    # Check null values
    checks = check_unknown_and_nulls(config)
    if checks["null_values"]:
        errors.append(f"Null/empty values in required sections: {checks['null_values']}")

    # Only check live mode invariants if basic validation passes
    if not errors:
        live_issues = check_live_mode_invariants(config)
        if live_issues:
            errors.extend(live_issues)

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }


def main(*args, **kwargs) -> int:
    """Main CLI function for SSOT validation."""
    if len(sys.argv) < 3 or sys.argv[1] != "--config":
        print("Usage: python tools/ssot_validate.py --config <config_file>", file=sys.stderr)
        return 1

    config_path = sys.argv[2]
    config_file = Path(config_path)

    if not config_file.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        return 1

    try:
        if config_file.suffix.lower() in ['.yaml', '.yml']:
            import yaml
            with open(config_file, 'r', encoding='utf-8') as f:
                config = yaml.safe_load(f)
        elif config_file.suffix.lower() == '.toml':
            try:
                import tomllib
                with open(config_file, 'rb') as f:
                    config = tomllib.load(f)
            except ImportError:
                import tomli
                with open(config_file, 'rb') as f:
                    config = tomli.load(f)
        else:
            with open(config_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
    except Exception as e:
        print(f"Error reading config file: {e}", file=sys.stderr)
        return 1

    result = validate_config(config)

    if not result["valid"]:
        for error in result["errors"]:
            print(error, file=sys.stderr)

        # Return specific exit codes based on error type
        error_str = str(result["errors"])
        if "Unknown top-level keys" in error_str:
            return 20
        elif "null" in error_str.lower() or "empty" in error_str.lower():
            return 30
        elif "Missing required keys" in error_str:
            return 50
        elif "live" in error_str.lower() or "invariant" in error_str.lower():
            return 401
        else:
            return 1

    print("Configuration is valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())