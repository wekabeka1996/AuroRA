#!/usr/bin/env python
"""Tests for DRO Lambda Autotuner"""
import json, tempfile, subprocess, yaml, math
from pathlib import Path

def test_dro_lambda_autotuner():
    """Test DRO lambda autotuner with synthetic data."""
    
    script_path = Path(__file__).parent.parent.parent / 'tools' / 'dro_lambda_autotune.py'
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        # Setup test files
        gating_log = tmppath / 'gating.jsonl'
        audit_json = tmppath / 'audit.json'
        risk_config = tmppath / 'risk.yaml'
        
        # Synthetic gating log with escalating penalties
        log_entries = []
        for i in range(20):
            penalty = 0.05 + i * 0.01  # Escalating penalty 0.05 -> 0.24
            entry = {
                "run_id": f"run_{i:03d}",
                "metric": "dro_penalty",
                "value": penalty,
                "message": f"metric=dro_penalty value={penalty} threshold=0.2"
            }
            log_entries.append(entry)
        
        with gating_log.open('w') as f:
            for entry in log_entries:
                f.write(json.dumps(entry) + '\n')
        
        # Synthetic audit with stress signals
        audit_data = {
            "drawdown": 0.15,  # Moderate stress
            "sharpe_ratio": 0.8,  # Slight degradation  
            "var_ratio_rb": 1.2   # Elevated volatility
        }
        with audit_json.open('w') as f:
            json.dump(audit_data, f)
        
        # Initial risk config
        initial_config = {
            "lambda": 1.0,
            "lambda_bounds": {"min": 0.1, "max": 3.0}
        }
        with risk_config.open('w') as f:
            yaml.safe_dump(initial_config, f)
        
        # Test 1: Dry run with escalating penalties should increase lambda
        result = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(gating_log),
            '--audit-json', str(audit_json), 
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        assert result.returncode == 2, f"Expected dry-run exit=2, got {result.returncode}: {result.stderr}"
        
        decision = json.loads(result.stdout.strip())
        assert decision['changed'] == True, "Should detect change needed"
        assert decision['lambda_after'] > decision['lambda_before'], "Lambda should increase with penalties"
        assert 'penalty_avg' in decision['meta'], "Should include penalty statistics"
        
        # Test 2: Apply changes
        result = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(gating_log),
            '--audit-json', str(audit_json),
            '--risk-config', str(risk_config)
        ], capture_output=True, text=True)
        
        assert result.returncode == 0, f"Expected success exit=0, got {result.returncode}: {result.stderr}"
        
        # Verify config updated
        with risk_config.open('r') as f:
            updated_config = yaml.safe_load(f)
        
        assert updated_config['lambda'] > 1.0, "Lambda should be increased"
        assert 'lambda_meta' in updated_config, "Should include metadata"
        assert 'last_update' in updated_config['lambda_meta'], "Should record update time"
        
        # Test 3: Monotonic response - higher penalties should yield higher lambda
        high_penalty_log = tmppath / 'high_penalty.jsonl'
        with high_penalty_log.open('w') as f:
            for i in range(10):
                penalty = 0.5 + i * 0.05  # Very high penalties
                entry = {
                    "run_id": f"stress_{i:03d}",
                    "metric": "dro_penalty", 
                    "value": penalty,
                    "message": f"metric=dro_penalty value={penalty}"
                }
                f.write(json.dumps(entry) + '\n')
        
        result = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(high_penalty_log),
            '--audit-json', str(audit_json),
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        high_penalty_decision = json.loads(result.stdout.strip())
        
        # Should produce higher lambda than moderate penalties
        assert high_penalty_decision['lambda_after'] > decision['lambda_after'], \
            "Higher penalties should yield higher lambda (monotonic response)"
        
        # Test 4: Bounds enforcement
        extreme_config = initial_config.copy()
        extreme_config['lambda_bounds'] = {'min': 0.5, 'max': 1.2}
        
        with risk_config.open('w') as f:
            yaml.safe_dump(extreme_config, f)
        
        result = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(high_penalty_log),
            '--audit-json', str(audit_json),
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        bounded_decision = json.loads(result.stdout.strip())
        assert bounded_decision['lambda_after'] <= 1.2, "Should respect max bound"
        
        # Test 5: No data handling
        empty_log = tmppath / 'empty.jsonl'
        empty_log.touch()
        
        result = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(empty_log),
            '--audit-json', str(audit_json),
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        empty_decision = json.loads(result.stdout.strip())
        assert empty_decision['changed'] == False, "No change with no data"
        assert empty_decision['meta']['reason'] == 'no_penalty_data', "Should indicate no data"

def test_stress_signal_integration():
    """Test that stress signals amplify lambda adjustments."""
    
    script_path = Path(__file__).parent.parent.parent / 'tools' / 'dro_lambda_autotune.py'
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        gating_log = tmppath / 'gating.jsonl'
        low_stress_audit = tmppath / 'low_stress.json'
        high_stress_audit = tmppath / 'high_stress.json'
        risk_config = tmppath / 'risk.yaml'
        
        # Identical penalty history - use lower penalty to see stress effect
        with gating_log.open('w') as f:
            for i in range(10):
                penalty = 0.08  # Lower penalty to see stress amplification
                entry = {"metric": "dro_penalty", "value": penalty, "run_id": f"run_{i}"}
                f.write(json.dumps(entry) + '\n')
        
        # Low stress audit
        with low_stress_audit.open('w') as f:
            json.dump({"drawdown": 0.01, "sharpe_ratio": 1.2, "var_ratio_rb": 0.9}, f)
        
        # High stress audit  
        with high_stress_audit.open('w') as f:
            json.dump({"drawdown": 0.3, "sharpe_ratio": 0.5, "var_ratio_rb": 2.0}, f)
        
        # Initial config
        with risk_config.open('w') as f:
            yaml.safe_dump({"lambda": 1.0, "lambda_bounds": {"min": 0.1, "max": 3.0}}, f)
        
        # Test low stress
        result_low = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(gating_log),
            '--audit-json', str(low_stress_audit),
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        # Test high stress
        result_high = subprocess.run([
            'python', str(script_path),
            '--gating-log', str(gating_log),
            '--audit-json', str(high_stress_audit),
            '--risk-config', str(risk_config),
            '--dry-run'
        ], capture_output=True, text=True)
        
        decision_low = json.loads(result_low.stdout.strip())
        decision_high = json.loads(result_high.stdout.strip())
        
        # High stress should yield higher lambda for same penalty
        assert decision_high['lambda_after'] > decision_low['lambda_after'], \
            "High stress signals should amplify lambda increase"
        
        # Verify stress signals recorded
        assert 'stress_signals' in decision_high['meta'], "Should record stress signals"
        assert decision_high['meta']['stress_multiplier'] > decision_low['meta']['stress_multiplier'], \
            "Stress multiplier should be higher for high stress"

if __name__ == '__main__':
    test_dro_lambda_autotuner()
    test_stress_signal_integration()
    print("✓ All DRO lambda autotuner tests passed")