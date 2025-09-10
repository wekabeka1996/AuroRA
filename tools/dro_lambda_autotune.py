#!/usr/bin/env python
"""DRO Lambda Autotuner

Adaptively computes DRO lambda parameter from historical penalty signals and risk indicators.

Reads:
  * Gating log JSONL (dro_penalty_avg values over time)
  * DCTS audit JSON (drawdown/sharpe signals if present)
  * configs/risk.yaml (current lambda and bounds)
Computes adaptive lambda using:
  - Monotonic response to penalty magnitude (higher penalty -> higher lambda)
  - Stress signal integration (drawdown, sharpe degradation)
  - Smoothing and stability constraints
Writes updated configs/risk.yaml with metadata.

Exit codes:
  0 - applied changes
  2 - dry-run only  
  3 - fatal error (schema / IO)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import yaml

# ---------------- Helpers ----------------

def load_yaml(path: Path) -> dict[str, Any]:
    """Load YAML file, return empty dict if missing."""
    try:
        with path.open('r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}

def write_yaml(path: Path, data: dict[str, Any]):
    """Atomic YAML write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    with tmp.open('w', encoding='utf-8') as f:
        yaml.safe_dump(data, f, sort_keys=True)
    tmp.replace(path)

def load_gating_log(path: Path, window: int = 50) -> list[dict[str, Any]]:
    """Load recent gating log entries."""
    entries = []
    try:
        with path.open('r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        entry = json.loads(line)
                        entries.append(entry)
                    except json.JSONDecodeError:
                        continue
    except FileNotFoundError:
        return []

    # Return most recent window entries
    return entries[-window:] if len(entries) > window else entries

def extract_dro_penalties(entries: list[dict[str, Any]]) -> list[float]:
    """Extract dro_penalty values from gating log entries."""
    penalties = []
    for entry in entries:
        try:
            # Look for dro_penalty in message field or direct field
            if 'message' in entry and 'dro_penalty' in entry['message']:
                # Parse from message string
                msg = entry['message']
                if 'value=' in msg:
                    value_part = msg.split('value=')[1].split()[0]
                    penalties.append(float(value_part))
            elif 'value' in entry and entry.get('metric') == 'dro_penalty':
                penalties.append(float(entry['value']))
        except (ValueError, KeyError):
            continue
    return penalties

def compute_stress_signals(audit_path: Path) -> dict[str, float]:
    """Extract stress indicators from audit."""
    try:
        with audit_path.open('r', encoding='utf-8') as f:
            audit = json.load(f)

        stress = {}

        # Drawdown signal (higher = more stress)
        if 'drawdown' in audit:
            stress['drawdown'] = float(audit['drawdown'])

        # Sharpe degradation (lower = more stress)
        if 'sharpe_ratio' in audit:
            sharpe = float(audit['sharpe_ratio'])
            stress['sharpe_deficit'] = max(0, 1.0 - sharpe)  # 1-sharpe as stress

        # Volatility signal
        if 'var_ratio_rb' in audit:
            stress['volatility'] = float(audit['var_ratio_rb'])

        return stress
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return {}

def compute_adaptive_lambda(
    penalties: list[float],
    stress_signals: dict[str, float],
    current_lambda: float,
    bounds: dict[str, float]
) -> tuple[float, dict[str, Any]]:
    """Compute adaptive lambda with monotonic penalty response."""

    if not penalties:
        return current_lambda, {"reason": "no_penalty_data", "penalty_count": 0}

    # Base penalty signal (recent average)
    penalty_avg = statistics.mean(penalties[-10:]) if len(penalties) >= 3 else statistics.mean(penalties)
    penalty_p95 = statistics.quantiles(penalties, n=20)[18] if len(penalties) >= 10 else max(penalties)

    # Monotonic response: higher penalty -> higher lambda
    base_multiplier = 1.0
    if penalty_avg > 0.1:  # Significant penalty threshold
        base_multiplier = 1.0 + min(penalty_avg * 2.0, 1.5)  # Cap at 2.5x

    # Stress amplification
    stress_multiplier = 1.0
    if stress_signals:
        drawdown_stress = stress_signals.get('drawdown', 0.0)
        sharpe_stress = stress_signals.get('sharpe_deficit', 0.0)
        vol_stress = min(stress_signals.get('volatility', 1.0), 2.0)

        stress_multiplier = 1.0 + 0.5 * (drawdown_stress + sharpe_stress + vol_stress * 0.3)

    # Combine signals
    target_lambda = current_lambda * base_multiplier * stress_multiplier

    # Apply bounds and smoothing (30% max change per update)
    min_lambda = bounds.get('min', 0.1)
    max_lambda = bounds.get('max', 3.0)
    max_change = 0.3 * current_lambda

    target_lambda = max(min_lambda, min(max_lambda, target_lambda))
    if abs(target_lambda - current_lambda) > max_change:
        target_lambda = current_lambda + math.copysign(max_change, target_lambda - current_lambda)

    # Metadata
    meta = {
        "penalty_avg": round(penalty_avg, 4),
        "penalty_p95": round(penalty_p95, 4),
        "penalty_count": len(penalties),
        "base_multiplier": round(base_multiplier, 3),
        "stress_multiplier": round(stress_multiplier, 3),
        "stress_signals": stress_signals,
        "bounded_change": abs(target_lambda - current_lambda) >= max_change * 0.99,
        "reason": "adaptive_update"
    }

    return target_lambda, meta

# ---------------- Main ----------------

def main():
    parser = argparse.ArgumentParser(description="DRO Lambda Autotuner")
    parser.add_argument('--gating-log', type=Path, default='artifacts/ci/gating_state.jsonl',
                       help='Gating log JSONL file')
    parser.add_argument('--audit-json', type=Path, default='summary_r1.json',
                       help='DCTS audit JSON file')
    parser.add_argument('--risk-config', type=Path, default='configs/risk.yaml',
                       help='Risk config YAML file')
    parser.add_argument('--dry-run', action='store_true',
                       help='Show changes without applying')
    parser.add_argument('--window', type=int, default=50,
                       help='Lookback window for penalty history')

    args = parser.parse_args()

    try:
        # Load inputs
        gating_entries = load_gating_log(args.gating_log, args.window)
        penalties = extract_dro_penalties(gating_entries)
        stress_signals = compute_stress_signals(args.audit_json)
        risk_config = load_yaml(args.risk_config)

        # Current lambda and bounds
        current_lambda = risk_config.get('lambda', 1.0)
        bounds = risk_config.get('lambda_bounds', {'min': 0.1, 'max': 3.0})

        # Compute adaptive lambda
        new_lambda, meta = compute_adaptive_lambda(penalties, stress_signals, current_lambda, bounds)

        # Decision
        changed = abs(new_lambda - current_lambda) > 1e-6

        # Output decision log
        decision = {
            "timestamp": time.time(),
            "tool": "dro_lambda_autotune",
            "lambda_before": current_lambda,
            "lambda_after": new_lambda,
            "changed": changed,
            "meta": meta
        }

        print(json.dumps(decision))

        if changed and not args.dry_run:
            # Update config
            risk_config['lambda'] = round(new_lambda, 4)
            risk_config.setdefault('lambda_meta', {}).update({
                "last_update": time.time(),
                "update_reason": meta["reason"],
                "penalty_history_size": meta["penalty_count"]
            })

            write_yaml(args.risk_config, risk_config)
            sys.exit(0)  # Applied changes
        elif changed:
            sys.exit(2)  # Dry-run with changes
        else:
            sys.exit(0)  # No changes needed

    except Exception as e:
        print(f"FATAL: {e}", file=sys.stderr)
        sys.exit(3)

if __name__ == '__main__':
    main()
