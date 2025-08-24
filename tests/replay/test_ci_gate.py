import json
from pathlib import Path
from living_latent.core.replay.summarize import check_ci_thresholds

CFG_BASE = {
    'alpha_target': 0.10,
    'coverage_tolerance': 0.03,
    'coverage_ema_tolerance': 0.03,
    'ctr_min': 0.95,
    'dcts_min': None,
    'max_churn_per_1k': 25,
    'max_exec_block_rate': 0.40,
    'tau_drift_ema_max': 0.02,
    'fail_fast': True,
}

def make_summary(**over):
    base = {
        'coverage_empirical': 0.905,
        'coverage_ema_final': 0.902,
        'alpha_target': 0.10,
        'tvf_ctr': {'ctr': 0.97},
        'exec_block_rate': 0.10,
        'decision_churn_per_1k': 12.0,
        'tau_drift_ema': 0.01,
    }
    base.update(over)
    return base


def test_ci_gate_pass():
    summary = make_summary()
    decision, violations = check_ci_thresholds(summary, CFG_BASE)
    assert decision == 'pass'
    assert violations == []
    assert summary['ci']['decision'] == 'pass'


def test_ci_gate_fail_coverage():
    summary = make_summary(coverage_empirical=0.86)  # below 0.9 - tol=0.03 => threshold 0.87
    decision, violations = check_ci_thresholds(summary, CFG_BASE)
    assert decision == 'fail'
    assert 'coverage_empirical' in violations


def test_ci_gate_fail_ctr():
    summary = make_summary()
    summary['tvf_ctr']['ctr'] = 0.90
    decision, violations = check_ci_thresholds(summary, CFG_BASE)
    assert decision == 'fail'
    assert 'tvf_ctr' in violations


def test_ci_gate_fail_churn():
    summary = make_summary(decision_churn_per_1k=100.0)
    decision, violations = check_ci_thresholds(summary, CFG_BASE)
    assert decision == 'fail'
    assert 'decision_churn_per_1k' in violations


def test_ci_gate_pass_churn_edge():
    # exactly at threshold should pass
    summary = make_summary(decision_churn_per_1k=CFG_BASE['max_churn_per_1k'])
    decision, violations = check_ci_thresholds(summary, CFG_BASE)
    assert decision == 'pass'
    assert violations == []


def test_ci_gate_fail_fast_short_circuit():
    cfg = dict(CFG_BASE)
    cfg['fail_fast'] = True
    # Make both coverage and ctr fail; expect only first violation captured
    summary = make_summary(coverage_empirical=0.80)
    summary['tvf_ctr']['ctr'] = 0.50
    decision, violations = check_ci_thresholds(summary, cfg)
    assert decision == 'fail'
    assert violations == ['coverage_empirical']  # fail-fast stops here


def test_ci_gate_multiple_violations_no_fail_fast():
    cfg = dict(CFG_BASE)
    cfg['fail_fast'] = False
    summary = make_summary(coverage_empirical=0.80)
    summary['tvf_ctr']['ctr'] = 0.50
    decision, violations = check_ci_thresholds(summary, cfg)
    assert decision == 'fail'
    assert set(violations) >= {'coverage_empirical', 'tvf_ctr'}
