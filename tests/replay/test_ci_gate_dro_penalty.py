import math
from living_latent.core.replay.summarize import check_ci_thresholds

CFG = {
    'fail_fast': True,
    'max_dro_penalty': 0.50,  # ceiling
}


def test_ci_gate_dro_penalty_pass():
    summary = {
        'acceptance': {
            'dro_penalty': 0.40,
        }
    }
    decision, violations = check_ci_thresholds(summary, CFG)
    assert decision == 'pass'
    assert violations == []


def test_ci_gate_dro_penalty_fail():
    summary = {
        'acceptance': {
            'dro_penalty': 0.51,
        }
    }
    decision, violations = check_ci_thresholds(summary, CFG)
    assert decision == 'fail'
    assert 'dro_penalty' in violations


def test_ci_gate_dro_penalty_missing_counts_as_violation():
    summary = {
        'acceptance': {}
    }
    decision, violations = check_ci_thresholds(summary, CFG)
    assert decision == 'fail'
    assert 'dro_penalty' in violations
