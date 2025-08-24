import json, shutil, tempfile, os
from pathlib import Path
import subprocess
import sys

import pytest

# We assume run_r0.py reads config via --config and --profile and expects logs jsonl.
# We'll craft minimal config with alpha.proxy_eval thresholds small so we can force degrade/recover quickly.

MIN_BASE_CONFIG = {
  'icp': {'alpha_target': 0.1},
  'acceptance': {},
  'metrics': {'enabled': False},
  'execution': {'gating': {}},
  'alpha': {
    'mode': 'adaptive',
    'static_value': 0.123,
    'proxy_eval': {
      'state_file': 'artifacts/state/alpha_proxy_state.json',
      'degrade_runs': 2,
      'recover_runs': 2,
      'corr_min_synth': 0.8,
      'corr_min_real_p25': 0.5
    }
  }
}

PRED_LINE = json.dumps({'mu':0.0,'sigma':0.1,'lo':-0.2,'hi':0.2,'y':0.0})

REPORT_GOOD = {
  'synthetic': [{'corr': 0.95}],
  'real': {'p25': 0.6}
}
REPORT_BAD = {
  'synthetic': [{'corr': 0.40}],
  'real': {'p25': 0.2}
}

PROJECT_ROOT = Path(__file__).resolve().parents[2]
RUN_CMD = [sys.executable, str(PROJECT_ROOT / 'living_latent' / 'scripts' / 'run_r0.py'), '--logs_dir', 'logs', '--config', 'config.yaml', '--profile', 'default']

@pytest.fixture()
def tmp_env():
  d = tempfile.mkdtemp(prefix='alpha_fail_safe_')
  cwd = os.getcwd()
  os.chdir(d)
  try:
    Path('logs').mkdir()
    with open('logs/pred_0.jsonl', 'w', encoding='utf-8') as f:
      for _ in range(10):
        f.write(PRED_LINE + '\n')
    import yaml  # write config
    with open('config.yaml', 'w', encoding='utf-8') as f:
      yaml.safe_dump({'profiles': {'default': MIN_BASE_CONFIG}}, f)
    yield Path(d)
  finally:
    os.chdir(cwd)
    shutil.rmtree(d)


def _write_report(payload):
    Path('artifacts/aci_eval').mkdir(parents=True, exist_ok=True)
    with open('artifacts/aci_eval/report.json','w',encoding='utf-8') as f:
        json.dump(payload, f)


def _run_once():
  env = dict(os.environ)
  root = str(PROJECT_ROOT)
  env['PYTHONPATH'] = root + (os.pathsep + env['PYTHONPATH'] if 'PYTHONPATH' in env else '')
  cp = subprocess.run(RUN_CMD + ['--summary_out','summary.json'], capture_output=True, text=True, env=env)
  assert cp.returncode == 0, cp.stderr
  with open('summary.json','r',encoding='utf-8') as f:
    return json.load(f)


def test_fail_safe_degrade_and_recover(tmp_env):
    # Start with GOOD report -> remain adaptive
    _write_report(REPORT_GOOD)
    s1 = _run_once()
    assert s1.get('alpha_mode') == 'adaptive'
    # Two BAD reports to cross degrade_runs=2 threshold
    _write_report(REPORT_BAD)
    s2 = _run_once()
    _write_report(REPORT_BAD)
    s3 = _run_once()
    assert s3.get('alpha_mode') == 'static', s3
    assert abs(s3.get('alpha_static_value') - 0.123) < 1e-9
    # Two GOOD reports to recover
    _write_report(REPORT_GOOD)
    s4 = _run_once()
    _write_report(REPORT_GOOD)
    s5 = _run_once()
    assert s5.get('alpha_mode') == 'adaptive', s5
