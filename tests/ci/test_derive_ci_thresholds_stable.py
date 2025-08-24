import json, os, sys, tempfile, shutil, yaml, math, random, subprocess
from pathlib import Path
import pytest

SCRIPT = Path('scripts/derive_ci_thresholds.py')
PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Helper to fabricate summary JSON objects with required keys

def make_summary(idx: int, base_cov: float, jitter: float = 0.002):
    cov = base_cov + random.uniform(-jitter, jitter)
    dcts = 0.97 + random.uniform(-0.01, 0.0)
    ctr = 0.985 + random.uniform(-0.01, 0.0)
    churn = 8.0 + random.uniform(-0.5, 0.5)
    dro_pen = 0.02 + random.uniform(-0.005, 0.005)
    tau = 0.015 + random.uniform(-0.003, 0.003)
    return {
        'coverage_empirical': cov,
        'tvf_ctr': {'ctr': ctr},
        'tvf2': {'dcts': dcts},
        'decision_churn_per_1k': churn,
        'acceptance': {'dro_penalty': dro_pen},
        'r1': {'tau_drift_ema': tau},
        'run_id': f'run_{idx}'
    }

@pytest.fixture()
def tmp_summaries():
    d = tempfile.mkdtemp(prefix='derive_ci_')
    try:
        rnd = random.Random(123)
        alpha_target = 0.10
        target_cov = 1 - alpha_target
        # create 25 stable summaries
        for i in range(25):
            s = make_summary(i, target_cov)
            with open(Path(d)/f'summary_{i:04d}.json','w',encoding='utf-8') as f:
                json.dump(s, f)
        yield Path(d)
    finally:
        shutil.rmtree(d)


def run_derive(dir_path: Path, out_yaml: Path):
    env = dict(os.environ)
    env['PYTHONPATH'] = str(PROJECT_ROOT)
    cmd = [sys.executable, str(SCRIPT), '--summaries', str(dir_path), '--out', str(out_yaml), '--alpha-target','0.10','--force']
    return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_derive_thresholds_stable_sample(tmp_summaries, tmp_path):
    out_yaml = tmp_path / 'ci_thresholds.yaml'
    cp = run_derive(tmp_summaries, out_yaml)
    assert cp.returncode == 0, cp.stdout + '\n' + cp.stderr
    assert out_yaml.exists()
    data = yaml.safe_load(out_yaml.read_text(encoding='utf-8'))
    assert 'thresholds' in data and 'meta' in data
    th = data['thresholds']
    # All expected keys present (may be None if insufficient but with 25 samples should be numeric)
    numeric_keys = ['coverage_tolerance','ctr_min','dcts_min','max_churn_per_1k','max_dro_penalty','tau_drift_ema_max']
    for k in numeric_keys:
        assert isinstance(th.get(k), (int,float)) and not math.isnan(th[k]), f"missing or nan {k}"
    # Check coverage tolerance within clamped range
    assert 0.02 <= th['coverage_tolerance'] <= 0.05
    meta = data['meta']
    assert meta.get('eligible_ratio',0) >= 0.7
    assert len(meta.get('eligible_keys',[])) >= 5
    # dcts_min >= 0.90 enforced
    assert th['dcts_min'] >= 0.90

