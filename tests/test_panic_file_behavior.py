#!/usr/bin/env python
"""Tests for panic file behavior in CI gating"""
import json, tempfile, yaml, os
from pathlib import Path
import pytest

def test_panic_file_disables_hard_gating():
    """Test that panic file existence disables hard gating."""
    
    # Import the gating module locally to avoid import issues
    import sys
    sys.path.append('.')
    
    from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        # Setup config with panic file
        panic_file = tmppath / 'panic_disable_hard'
        config = {
            'hard_enabled': True,
            'panic_file': str(panic_file),
            'enter_warn_runs': 1,
            'exit_warn_runs': 1, 
            'enter_watch_runs': 1,
            'cooldown_runs': 1,
            'persistence_file': str(tmppath / 'gating.jsonl')
        }
        
        # Hard candidate metric spec
        metric_specs = [
            MetricSpec(
                name='test_metric',
                source_key='test_value',
                threshold_key='test_threshold', 
                relation='<=',
                hard_candidate=True
            )
        ]
        
        # Create state machine
        state_machine = CIGatingStateMachine(
            cfg=config,
            metric_specs=metric_specs
        )
        
        # Test data: metric violates threshold
        summary = {'test_value': 100.0}
        thresholds = {
            'test_threshold': 50.0,
            'hard_meta': {
                'test_threshold': {
                    'hard_enabled': True,
                    'hard_reason': 'test_violation'
                }
            }
        }
        
        # Test 1: Without panic file - should get hard failure
        events = state_machine.evaluate_batch('run_001', summary, thresholds)
        
        # Find the test metric event
        test_event = next(ev for ev in events if ev.metric == 'test_metric')
        assert test_event.violation == True, "Should detect violation"
        assert '[CI-GATING][HARD]' in test_event.message, "Should flag hard gating failure"
        assert state_machine.any_hard_failure(events), "Should detect hard failure"
        
        # Test 2: Create panic file - should disable hard gating  
        panic_file.touch()
        
        events_panic = state_machine.evaluate_batch('run_002', summary, thresholds)
        
        # Find the test metric event
        test_event_panic = next(ev for ev in events_panic if ev.metric == 'test_metric')
        assert test_event_panic.violation == True, "Should still detect violation"
        assert '[PANIC] hard gating disabled' in test_event_panic.message, "Should log panic mode"
        assert '[CI-GATING][HARD]' not in test_event_panic.message, "Should NOT flag hard failure"
        assert not state_machine.any_hard_failure(events_panic), "Should NOT detect hard failure"
        
        # Test 3: Remove panic file - hard gating should re-enable
        panic_file.unlink()
        
        events_restored = state_machine.evaluate_batch('run_003', summary, thresholds)
        
        test_event_restored = next(ev for ev in events_restored if ev.metric == 'test_metric')
        assert test_event_restored.violation == True, "Should detect violation"
        assert '[CI-GATING][HARD]' in test_event_restored.message, "Should flag hard failure again"
        assert '[PANIC]' not in test_event_restored.message, "Should not log panic mode"
        assert state_machine.any_hard_failure(events_restored), "Should detect hard failure again"

def test_panic_file_config_missing():
    """Test behavior when panic_file not configured."""
    
    import sys
    sys.path.append('.')
    
    from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        # Config without panic_file
        config = {
            'hard_enabled': True,
            'enter_warn_runs': 1,
            'exit_warn_runs': 1,
            'enter_watch_runs': 1, 
            'cooldown_runs': 1,
            'persistence_file': str(tmppath / 'gating.jsonl')
        }
        
        metric_specs = [
            MetricSpec(
                name='test_metric',
                source_key='test_value',
                threshold_key='test_threshold',
                relation='<=',
                hard_candidate=True
            )
        ]
        
        state_machine = CIGatingStateMachine(
            cfg=config,
            metric_specs=metric_specs
        )
        
        # Test data: metric violates threshold
        summary = {'test_value': 100.0}
        thresholds = {
            'test_threshold': 50.0,
            'hard_meta': {
                'test_threshold': {
                    'hard_enabled': True,
                    'hard_reason': 'test_violation'
                }
            }
        }
        
        # Should work normally without panic file config
        events = state_machine.evaluate_batch('run_001', summary, thresholds)
        
        test_event = next(ev for ev in events if ev.metric == 'test_metric')
        assert test_event.violation == True, "Should detect violation"
        assert '[CI-GATING][HARD]' in test_event.message, "Should flag hard failure"
        assert '[PANIC]' not in test_event.message, "Should not mention panic"
        assert state_machine.any_hard_failure(events), "Should detect hard failure"

def test_panic_file_soft_metrics_unaffected():
    """Test that panic file only affects hard gating, not soft gating."""
    
    import sys
    sys.path.append('.')
    
    from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
    
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)
        
        panic_file = tmppath / 'panic_disable_hard'
        config = {
            'hard_enabled': True,
            'panic_file': str(panic_file),
            'enter_warn_runs': 1,
            'exit_warn_runs': 1,
            'enter_watch_runs': 1,
            'cooldown_runs': 1,
            'persistence_file': str(tmppath / 'gating.jsonl')
        }
        
        # Mix of hard and soft metrics
        metric_specs = [
            MetricSpec(
                name='hard_metric',
                source_key='hard_value',
                threshold_key='hard_threshold',
                relation='<=',
                hard_candidate=True
            ),
            MetricSpec(
                name='soft_metric',
                source_key='soft_value', 
                threshold_key='soft_threshold',
                relation='<=',
                hard_candidate=False  # Soft metric
            )
        ]
        
        state_machine = CIGatingStateMachine(
            cfg=config,
            metric_specs=metric_specs
        )
        
        # Both metrics violate thresholds
        summary = {
            'hard_value': 100.0,
            'soft_value': 200.0
        }
        thresholds = {
            'hard_threshold': 50.0,
            'soft_threshold': 100.0,
            'hard_meta': {
                'hard_threshold': {
                    'hard_enabled': True,
                    'hard_reason': 'hard_violation'
                }
            }
        }
        
        # Create panic file
        panic_file.touch()
        
        events = state_machine.evaluate_batch('run_001', summary, thresholds)
        
        # Find events
        hard_event = next(ev for ev in events if ev.metric == 'hard_metric')
        soft_event = next(ev for ev in events if ev.metric == 'soft_metric')
        
        # Hard metric should be affected by panic
        assert hard_event.violation == True, "Hard metric should detect violation"
        assert '[PANIC] hard gating disabled' in hard_event.message, "Hard metric should show panic"
        assert '[CI-GATING][HARD]' not in hard_event.message, "Hard metric should not flag hard failure"
        
        # Soft metric should be unaffected by panic
        assert soft_event.violation == True, "Soft metric should detect violation"
        assert '[PANIC]' not in soft_event.message, "Soft metric should not mention panic"
        assert '[CI-GATING][HARD]' not in soft_event.message, "Soft metric should not flag hard failure"
        
        # No hard failures should be detected
        assert not state_machine.any_hard_failure(events), "Should not detect any hard failures"

if __name__ == '__main__':
    test_panic_file_disables_hard_gating()
    test_panic_file_config_missing()
    test_panic_file_soft_metrics_unaffected()
    print("✓ All panic file tests passed")