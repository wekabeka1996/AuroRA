import json
import math
from pathlib import Path

from scripts.derive_ci_thresholds import compute_thresholds


def _summary(idx, cov, dcts, ctr, churn, dro, tau):
    return {
        'coverage_empirical': cov,
        'alpha_target': 0.10,
        'tvf2': {'dcts': dcts},
        'tvf_ctr': {'ctr': ctr},
        'decision_churn_per_1k': churn,
        'acceptance': {'dro_penalty': dro},
        'r1': {'tau_drift_ema': tau},
    }


def test_enhanced_thresholds_percentiles(tmp_path):
    # Construct 6 synthetic summaries with spread values
    samples = [
        _summary(1, cov=0.88, dcts=0.91, ctr=0.955, churn=10, dro=0.010, tau=0.008),
        _summary(2, cov=0.89, dcts=0.92, ctr=0.960, churn=12, dro=0.012, tau=0.009),
        _summary(3, cov=0.905, dcts=0.93, ctr=0.958, churn=14, dro=0.013, tau=0.011),
        _summary(4, cov=0.91, dcts=0.935, ctr=0.962, churn=15, dro=0.014, tau=0.012),
        _summary(5, cov=0.893, dcts=0.925, ctr=0.956, churn=13, dro=0.016, tau=0.010),
        _summary(6, cov=0.907, dcts=0.94, ctr=0.959, churn=11, dro=0.018, tau=0.013),
    ]

    result = compute_thresholds(samples, alpha_target=0.10)
    th = result['thresholds']

    # coverage_tolerance present & clamped within [0.02,0.05]
    assert 'coverage_tolerance' in th
    assert 0.02 <= th['coverage_tolerance'] <= 0.05

    # dcts_min >= 0.90 and <= max observed dcts
    assert 'dcts_min' in th and 0.90 <= th['dcts_min'] <= max(s['tvf2']['dcts'] for s in samples)

    # ctr_min at least 0.95
    assert 'ctr_min' in th and th['ctr_min'] >= 0.95

    # max_churn_per_1k within clamp [15,40]
    assert 'max_churn_per_1k' in th
    assert 15 <= th['max_churn_per_1k'] <= 40

    # max_dro_penalty positive scaled
    assert 'max_dro_penalty' in th and th['max_dro_penalty'] > 0

    # tau_drift_ema_max within clamp [0.01,0.05]
    assert 'tau_drift_ema_max' in th
    assert 0.01 <= th['tau_drift_ema_max'] <= 0.05

    meta = result['meta']
    assert meta['sample_counts']['coverage_samples'] >= 5
    assert meta['sample_counts']['dcts_samples'] >= 5
    assert meta['sample_counts']['dro_penalty_samples'] >= 5
