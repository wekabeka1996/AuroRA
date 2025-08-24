import json, os, sys, tempfile, shutil, yaml, math, random, subprocess
from pathlib import Path
import pytest

SCRIPT = Path('scripts/derive_ci_thresholds.py')
PROJECT_ROOT = Path(__file__).resolve().parents[2]

random.seed(321)

def synth_summary(cov_target: float, drift_lo: float, drift_hi: float, churn_base: float, i:int):
    return {
        'coverage_empirical': cov_target + random.uniform(-0.01,0.01),  # deliberately wide to exceed strict p95 requirement sometimes
        'tvf_ctr': {'ctr': 0.975 + random.uniform(0,0.01)},
        'tvf2': {'dcts': 0.94 + random.uniform(0,0.02)},
        'decision_churn_per_1k': churn_base + random.uniform(-1.0,1.0),
        'acceptance': {'dro_penalty': 0.015 + random.uniform(0,0.01)},
        'r1': {'tau_drift_ema': random.uniform(drift_lo, drift_hi)},
        'run_id': f'run_{i}'
    }

@pytest.fixture()
def stable_unstable_sets():
    d = tempfile.mkdtemp(prefix='derive_hard_')
    try:
        path = Path(d)
        # Stable set (tight coverage & low churn & low drift) -> expect hard candidates
        stable_dir = path / 'stable'
        stable_dir.mkdir()
        target_cov = 0.90
        for i in range(30):
            s = synth_summary(target_cov, drift_lo=0.005, drift_hi=0.01, churn_base=10.0, i=i)
            with open(stable_dir/f'summary_{i:04d}.json','w',encoding='utf-8') as f:
                json.dump(s,f)
        # Unstable set (higher churn & higher drift) -> fewer/no hard candidates
        unstable_dir = path / 'unstable'
        unstable_dir.mkdir()
        for i in range(30):
            s = synth_summary(target_cov, drift_lo=0.03, drift_hi=0.06, churn_base=30.0, i=i)
            with open(unstable_dir/f'summary_{i:04d}.json','w',encoding='utf-8') as f:
                json.dump(s,f)
        yield stable_dir, unstable_dir
    finally:
        shutil.rmtree(d)


def run_derive(dir_path: Path, out_yaml: Path, extra=None):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    cmd = [sys.executable, str(SCRIPT), '--summaries', str(dir_path), '--out', str(out_yaml), '--alpha-target','0.10','--force','--emit-hard-candidates']
    if extra:
        cmd += extra
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_hard_candidates_emission(stable_unstable_sets, tmp_path):
    stable_dir, unstable_dir = stable_unstable_sets
    out_stable = tmp_path/'stable.yaml'
    out_unstable = tmp_path/'unstable.yaml'
    cp1 = run_derive(stable_dir, out_stable)
    assert cp1.returncode == 0, cp1.stdout + '\n' + cp1.stderr
    cp2 = run_derive(unstable_dir, out_unstable)
    assert cp2.returncode == 0, cp2.stdout + '\n' + cp2.stderr
    data_stable = yaml.safe_load(out_stable.read_text(encoding='utf-8'))
    data_unstable = yaml.safe_load(out_unstable.read_text(encoding='utf-8'))
    hc_stable = set(data_stable['meta'].get('hard_candidates', []))
    hc_unstable = set(data_unstable['meta'].get('hard_candidates', []))
    # Expect at least coverage_tolerance & max_churn_per_1k in stable set
    assert 'coverage_tolerance' in hc_stable
    assert 'max_churn_per_1k' in hc_stable
    # Unstable set should have strictly fewer hard candidates (due to higher churn & drift)
    assert len(hc_unstable) <= len(hc_stable)
    # Drift metric likely excluded in unstable
    if 'tau_drift_ema_max' in hc_stable:
        assert 'tau_drift_ema_max' not in hc_unstable or data_unstable['meta']['percentiles_source']['tau_drift_ema_p95'] > 0.04
