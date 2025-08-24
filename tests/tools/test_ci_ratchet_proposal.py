import json, tempfile, yaml, subprocess, sys
from pathlib import Path


def make_current(path: Path):
    data = {
        'thresholds': {
            'coverage_tolerance': 0.03,
            'dcts_min': 0.90,
            'max_churn_per_1k': 30.0
        },
        'meta': {'generated': 't'}
    }
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding='utf-8')


def make_proposal(path: Path, coverage_new=0.031, dcts_new=0.97, churn_new=10.0, include_none=False):
    proposal = {
        'new': {
            'thresholds': {
                'coverage_tolerance': coverage_new,
                'dcts_min': dcts_new,
                'max_churn_per_1k': churn_new,
                'tau_drift_ema_max': None if include_none else 0.02,
            },
            'meta': {'eligible_ratio': 0.9}
        }
    }
    path.write_text(json.dumps(proposal, indent=2), encoding='utf-8')


def run_ratchet(current, proposal, out, max_step=0.05):
    cmd = [sys.executable, 'tools/ci_ratchet.py', '--current', str(current), '--proposal', str(proposal), '--out', str(out), '--max-step', str(max_step), '--dryrun', '--exitcode-dryrun=0']
    return subprocess.run(cmd, capture_output=True, text=True)


def load_yaml(path: Path):
    return yaml.safe_load(path.read_text())


def test_ratchet_limits_step():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cur = d / 'cur.yaml'; prop = d / 'prop.json'; out = d / 'out.yaml'
        make_current(cur)
        # propose large upward jump for dcts_min (from 0.90 to 1.00) - should clamp at +5%
        make_proposal(prop, dcts_new=1.00)
        res = run_ratchet(cur, prop, out, max_step=0.05)
        assert res.returncode == 0, res.stderr
        y = load_yaml(out)
        # coverage within step -> adopt
        assert y['thresholds']['coverage_tolerance'] == 0.031
        # dcts_min 0.90 -> clamp to 0.945 (5% up)
        assert abs(y['thresholds']['dcts_min'] - 0.945) < 1e-6
        # churn 30 -> 10 large downward; clamp 5% down => 28.5
        assert abs(y['thresholds']['max_churn_per_1k'] - 28.5) < 1e-6
        # ratchet meta present
        assert 'ratchet' in y['meta']


def test_ratchet_skip_ineligible_none():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cur = d / 'cur.yaml'; prop = d / 'prop.json'; out = d / 'out.yaml'
        make_current(cur)
        make_proposal(prop, include_none=True)
        res = run_ratchet(cur, prop, out)
        assert res.returncode == 0
        y = load_yaml(out)
        # tau_drift_ema_max absent in current and proposed None -> should not appear
        assert 'tau_drift_ema_max' not in y['thresholds']


def test_ratchet_yaml_valid_output():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cur = d / 'cur.yaml'; prop = d / 'prop.json'; out = d / 'out.yaml'
        make_current(cur)
        make_proposal(prop)
        res = run_ratchet(cur, prop, out)
        assert res.returncode == 0
        # ensure YAML loads
        y = load_yaml(out)
        assert isinstance(y, dict) and 'thresholds' in y


def test_ci_ratchet_exitcode_compat():
    """Test exitcode compatibility for dryrun mode."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cur = d / 'cur.yaml'; prop = d / 'prop.json'; out = d / 'out.yaml'
        make_current(cur)
        make_proposal(prop)
        
        # Test case A: default behavior (exit=2)
        cmd_default = [sys.executable, 'tools/ci_ratchet.py', '--current', str(cur), '--proposal', str(prop), '--out', str(out), '--dryrun']
        result_default = subprocess.run(cmd_default, capture_output=True, text=True)
        assert result_default.returncode == 2, f"Default should exit=2, got {result_default.returncode}"
        
        # Test case B: legacy compatibility (exit=0)
        cmd_compat = [sys.executable, 'tools/ci_ratchet.py', '--current', str(cur), '--proposal', str(prop), '--out', str(out), '--dryrun', '--exitcode-dryrun=0']
        result_compat = subprocess.run(cmd_compat, capture_output=True, text=True)
        assert result_compat.returncode == 0, f"Compat mode should exit=0, got {result_compat.returncode}"
