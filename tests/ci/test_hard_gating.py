import json, os, shutil, tempfile, subprocess, sys
from pathlib import Path
import yaml
import pytest

RUN_R0 = Path('living_latent/scripts/run_r0.py')

BASE_PROFILE = {
  'icp': {'alpha_target': 0.1},
  'acceptance': {},
  'metrics': {'enabled': False},
  'execution': {'gating': {}},
  'ci_gating': {
    'enabled': True,
    'hard_enabled': True,
    'window_runs': 3,
    'enter_warn_runs': 1,
    'exit_warn_runs': 1,
  }
}

THRESHOLDS = {
  'surprisal_p95_max': 0.0001  # intentionally tiny threshold to guarantee violation
}

# MetricSpec in run_r0 uses names from config ci_gating.metrics; we emulate one metric mapping
# We'll gate on surprisal_p95 <= threshold; summary produces key 'surprisal_p95'.

PROJECT_ROOT = Path(__file__).resolve().parents[2]

@pytest.fixture()
def tmp_env():
  d = tempfile.mkdtemp(prefix='ci_hard_')
  cwd = os.getcwd()
  os.chdir(d)
  Path('logs').mkdir()
  # create simple log lines (values chosen arbitrarily)
  pred = {'mu':0.0,'sigma':0.1,'lo':-0.2,'hi':0.2,'y':0.5}
  import json as _json
  with open('logs/pred_0.jsonl','w',encoding='utf-8') as f:
    for _ in range(5):
      f.write(_json.dumps(pred)+'\n')
  prof = dict(BASE_PROFILE)
  prof['ci_gating']['metrics'] = [
    {'name':'surprisal','source_key':'surprisal_p95','threshold_key':'surprisal_p95_max','relation':'<=','hard_candidate':True}
  ]
  with open('config.yaml','w',encoding='utf-8') as f:
    yaml.safe_dump({'profiles': {'default': prof}}, f)
  Path('configs').mkdir(exist_ok=True)
  with open('configs/ci_thresholds.yaml','w',encoding='utf-8') as f:
    yaml.safe_dump(THRESHOLDS, f)
  try:
    yield Path(d)
  finally:
    os.chdir(cwd)
    shutil.rmtree(d)


def run_once():
  env = dict(os.environ)
  env['PYTHONPATH'] = str(PROJECT_ROOT)
  script = PROJECT_ROOT / 'living_latent' / 'scripts' / 'run_r0.py'
  cmd = [sys.executable, str(script), '--logs_dir','logs','--config','config.yaml','--profile','default','--summary_out','summary.json']
  return subprocess.run(cmd, capture_output=True, text=True, env=env)


def test_hard_gating_fail(tmp_env):
  cp = run_once()
  # Expect non-zero exit code 3 when hard gating violation occurs
  assert cp.returncode == 3, cp.stdout + '\n' + cp.stderr
  # Summary should indicate hard failure
  with open('summary.json','r',encoding='utf-8') as f:
    summary = json.load(f)
  assert summary.get('ci_hard_failed') is True
  # Log should contain HARD tag
  assert '[CI-GATING][HARD]' in cp.stdout
