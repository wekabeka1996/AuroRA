import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def make_summary(dir_path: Path, idx: int, dcts=0.95, churn=20.0, coverage=0.9):
    payload = {
        'coverage_empirical': coverage,
        'decision_churn_per_1k': churn,
        'tvf2': {
            'dcts': dcts,
            'dcts_robust': {'value': dcts},
        }
    }
    (dir_path / f'summary_{idx:03d}.json').write_text(json.dumps(payload), encoding='utf-8')


def test_derive_enable_hard():
    """Verify --enable-hard annotates thresholds with hard_meta for selected logical metric.

    Runtime override semantics will be covered in a dedicated integration test (pending) once
    a stable configuration layering helper is available in tests.
    """
    with tempfile.TemporaryDirectory() as td:
        base = Path(td)
        summaries = base / 'summaries'
        summaries.mkdir()
        # fabricate summaries giving consistent metrics
        for i in range(25):
            make_summary(summaries, i, dcts=0.96, churn=18.0 + (i % 3), coverage=0.90 + 0.005 * ((i % 4) - 2))

        out_yaml = base / 'thr.yaml'
        # Run derive with hard candidate emission then enable tvf2.dcts
        cmd = [
            sys.executable,
            'scripts/derive_ci_thresholds.py',
            '--summaries',
            str(summaries),
            '--out',
            str(out_yaml),
            '--force',
            '--emit-hard-candidates',
            '--enable-hard',
            'tvf2.dcts',
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode in (0, 2), res.stderr
        data = yaml.safe_load(out_yaml.read_text())
        assert 'hard_meta' in data and 'dcts_min' in data['hard_meta']
        assert data['hard_meta']['dcts_min']['hard_enabled'] is True

    # Further runtime checks deferred.
