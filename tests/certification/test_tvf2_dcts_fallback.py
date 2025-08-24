import json
from pathlib import Path

def test_derive_thresholds_fallback_to_base(tmp_path):
    summaries_dir = tmp_path / 'summaries'
    summaries_dir.mkdir()
    base_vals = [0.94, 0.95, 0.955, 0.945, 0.948, 0.947]
    for i, v in enumerate(base_vals):
        data = {
            'coverage_empirical': 0.9,
            'tvf2': {
                'dcts': v
                # no robust fields
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
    rep = json.loads(report_json.read_text())
    assert rep['new']['meta']['percentiles_source']['dcts_source'] == 'base'
