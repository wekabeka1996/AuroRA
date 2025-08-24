import json
from pathlib import Path

from scripts.derive_ci_thresholds import compute_thresholds


def _write_summary(tmp: Path, idx: int, dro: float, churn: float, dcts: float, cov: float):
    data = {
        "acceptance": {"dro_penalty": dro},
        "decision_churn_per_1k": churn,
        "tvf2": {"dcts": dcts},
        "coverage_empirical": cov,
    }
    (tmp / f"summary_{idx}.json").write_text(json.dumps(data), encoding="utf-8")


def test_compute_thresholds_basic(tmp_path):
    # Create synthetic summaries spanning a range
    _write_summary(tmp_path, 1, dro=0.010, churn=8.0, dcts=0.965, cov=0.895)
    _write_summary(tmp_path, 2, dro=0.015, churn=12.0, dcts=0.955, cov=0.905)
    _write_summary(tmp_path, 3, dro=0.020, churn=15.0, dcts=0.945, cov=0.910)
    _write_summary(tmp_path, 4, dro=0.030, churn=20.0, dcts=0.940, cov=0.885)
    # Add a 5th sample to satisfy production min_samples >=5 logic
    _write_summary(tmp_path, 5, dro=0.025, churn=18.0, dcts=0.950, cov=0.900)

    # Load json dicts
    summaries = []
    for fp in sorted(tmp_path.glob('summary_*.json')):
        summaries.append(json.loads(fp.read_text(encoding='utf-8')))

    result = compute_thresholds(summaries, alpha_target=0.10)
    assert 'thresholds' in result and 'meta' in result
    th = result['thresholds']

    # Required keys
    for key in ['max_dro_penalty', 'max_churn_per_1k', 'dcts_min']:
        assert key in th
        assert th[key] is not None

    # dcts_min should be >= 0.90 and <= max observed dcts
    assert 0.90 <= th['dcts_min'] <= 0.98

    # dro & churn thresholds above observed maxima (allow small safety factor)
    assert th['max_dro_penalty'] >= 0.03 * 0.99
    assert th['max_churn_per_1k'] >= 20.0 * 0.99

    # coverage delta key optional but if present it's finite
    if 'coverage_delta_abs_max' in th:
        assert th['coverage_delta_abs_max'] >= 0

    meta = result['meta']
    # Updated meta schema: 'samples_total' and min_samples requirement
    assert meta['samples_total'] == 5
    assert meta['alpha_target'] == 0.10
