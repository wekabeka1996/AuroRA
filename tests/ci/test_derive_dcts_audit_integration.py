import json, os, tempfile, yaml, time
from pathlib import Path
import subprocess, sys


def write_summary(dir_path: Path, idx: int, robust: float, base: float, churn: float=5.0, coverage: float=0.9):
    obj = {
        'coverage_empirical': coverage,
        'decision_churn_per_1k': churn,
        'tvf2': {
            'dcts': base,
            'dcts_robust': {'value': robust},
        }
    }
    (dir_path / f'summary_{idx:03d}.json').write_text(json.dumps(obj), encoding='utf-8')


def test_dcts_audit_var_ratio_integration():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        summaries_dir = d / 'summaries'
        summaries_dir.mkdir()
        # create 25 summaries with small robust variance vs base
        for i in range(25):
            # base oscillates a bit, robust tighter
            base = 0.80 + (0.01 * ((i % 5) - 2))  # variance > robust
            robust = 0.80 + (0.004 * ((i % 5) - 2))
            write_summary(summaries_dir, i, robust=robust, base=base)
        # craft audit json to reflect low var_ratio
        audit = {
            'counts': {'base': 25, 'robust': 25},
            'var_ratio': 0.5
        }
        audit_path = d / 'audit.json'
        audit_path.write_text(json.dumps(audit), encoding='utf-8')
        # ensure mtime is current (fresh)
        now = time.time()
        os.utime(audit_path, (now, now))
        out_yaml = d / 'ci_thresholds.yaml'
        cmd = [sys.executable, 'scripts/derive_ci_thresholds.py',
               '--summaries', str(summaries_dir),
               '--out', str(out_yaml), '--force',
               '--emit-hard-candidates',
               '--dcts-audit-json', str(audit_path),
               '--hard-min-samples', '20']
        res = subprocess.run(cmd, cwd=Path.cwd(), capture_output=True, text=True)
        assert res.returncode in (0,2), res.stderr
        # YAML produced
        assert out_yaml.exists(), 'thresholds yaml not written'
        data = yaml.safe_load(out_yaml.read_text())
        meta = data.get('meta', {})
        # var_ratio carried into meta
        assert 'var_ratio_rb' in meta and meta['var_ratio_rb'] == 0.5
        # hard candidates include dcts_min with var_ratio based reason
        reasons = meta.get('hard_candidate_reasons', {})
        assert 'dcts_min' in reasons
        assert 'var_ratio_rb<=' in reasons['dcts_min']
        # log line includes var_ratio
        assert 'var_ratio=0.5' in (res.stdout + res.stderr)
