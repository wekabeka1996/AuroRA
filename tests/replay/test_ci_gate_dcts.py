import json
from living_latent.core.replay.summarize import check_ci_thresholds

CFG = {
    'alpha_target': 0.1,
    'coverage_tolerance': 0.03,
    'coverage_ema_tolerance': 0.03,
    'ctr_min': 0.95,
    'dcts_min': 0.90,
    'max_churn_per_1k': 9999,
    'fail_fast': False,
}

def _base_summary(dcts: float | None, ctr: float = 0.96):
    return {
        'alpha_target': 0.1,
        'coverage_empirical': 0.92,  # meets target 0.9
        'coverage_ema_final': 0.91,
        'tvf2': {'dcts': dcts, 'ctr': ctr},
        'decision_churn_per_1k': 1.0,
    }


def test_ci_gate_dcts_fail_below():
    summary = _base_summary(0.87)
    decision, violations = check_ci_thresholds(summary, CFG)
    assert decision == 'fail'
    assert 'tvf_dcts' in violations


def test_ci_gate_dcts_pass_on_threshold():
    summary = _base_summary(0.90)
    decision, violations = check_ci_thresholds(summary, CFG)
    assert decision == 'pass', f"Unexpected violations: {violations}"
