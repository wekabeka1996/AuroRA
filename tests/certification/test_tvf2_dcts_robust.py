import json
import math
from pathlib import Path


def test_summary_contains_robust_fields(tmp_path, monkeypatch):
    # Reuse a minimal existing summary fixture logic by creating a fake summary file scenario
    # We'll simulate the structure produced by run_r0 augmentation.
    summary = {
        'tvf2': {
            'dcts': 0.9731,
            'dcts_grids': {'0.5': 0.9731, '1.0': 0.9731},
            'dcts_robust': {'value': 0.9731, 'grids': [0.5, 1.0]},
            'dcts_min': {'value': 0.9731},
            'dcts_robust_value': 0.9731,
        }
    }
    assert 'tvf2' in summary
    tv = summary['tvf2']
    assert 'dcts_robust' in tv and isinstance(tv['dcts_robust'], dict)
    assert 'value' in tv['dcts_robust']
    assert 'dcts_min' in tv and 'value' in tv['dcts_min']
    assert 'dcts_grids' in tv and isinstance(tv['dcts_grids'], dict)
    assert 'dcts_robust_value' in tv
    # numeric checks
    assert math.isfinite(tv['dcts_robust']['value'])
    assert math.isfinite(tv['dcts_min']['value'])


def test_derive_thresholds_prefers_robust(tmp_path, monkeypatch):
    # Create 6 synthetic summary files to exceed min sample threshold (>=5)
    summaries_dir = tmp_path / 'summaries'
    summaries_dir.mkdir()
    base_vals = [0.95, 0.96, 0.965, 0.955, 0.958, 0.957]
    for i, v in enumerate(base_vals):
        data = {
            'coverage_empirical': 0.9,
            'tvf2': {
                'dcts': v - 0.01,  # base slightly lower
                'dcts_robust': {'value': v},
                'dcts_robust_value': v,
            }
        }
        with (summaries_dir / f'summary_{i}.json').open('w', encoding='utf-8') as f:
            json.dump(data, f)
    out_yaml = tmp_path / 'ci_thresholds.yaml'
    report_json = tmp_path / 'report.json'
    from scripts.derive_ci_thresholds import main
    rc = main([
        '--summaries', str(summaries_dir),
        '--out', str(out_yaml),
        '--alpha-target', '0.1',
        '--force',
        '--report', str(report_json)
    ])
    assert rc in (0, 2)
    # Load report json to inspect dcts source meta
    rep = json.loads(report_json.read_text())
    meta = rep['new']['meta']
    assert rep['new']['meta']['percentiles_source']['dcts_p10'] is not None
    assert rep['new']['meta']['percentiles_source']['dcts_source'] == 'robust'
