import subprocess
import sys
import json
import os
import hashlib


def test_overlay_changes_expected_keys(tmp_path):
    # run print_effective_config for local_low and check file exists and contains expected keys
    repo = os.path.abspath(os.path.dirname(__file__) + '/../')
    cfg = os.path.join(repo, 'configs', 'default.toml')
    schema = os.path.join(repo, 'configs', 'schema.json')
    out = subprocess.run([sys.executable, os.path.join(repo, 'tools', 'print_effective_config.py'),
                          '--profile', 'local_low', '--config', cfg, '--schema', schema], capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + '\n' + out.stderr
    report = os.path.join(repo, 'reports', 'effective_local_low.toml')
    assert os.path.exists(report)
    data = open(report).read()
    assert 'execution.sla' in data or 'execution.sla.max_latency_ms' in data


def test_unknown_profile_exit_61(tmp_path):
    repo = os.path.abspath(os.path.dirname(__file__) + '/../')
    proc = subprocess.run([sys.executable, '-m', 'scripts.run_replay', '--profile', 'unknown_foo',
                           '--config', os.path.join(repo,'configs','default.toml'),
                           '--schema', os.path.join(repo,'configs','schema.json')], capture_output=True, text=True)
    # process should exit with code 61
    assert proc.returncode == 61
    assert 'PROFILE: unknown profile unknown_foo' in proc.stdout


def test_effective_config_validates(tmp_path):
    repo = os.path.abspath(os.path.dirname(__file__) + '/../')
    # ensure validator is available and run on generated effective_local_low.toml
    cfg = os.path.join(repo, 'reports', 'effective_local_low.toml')
    if not os.path.exists(cfg):
        # generate it
        subprocess.run([sys.executable, os.path.join(repo, 'tools', 'print_effective_config.py'),
                        '--profile', 'local_low', '--config', os.path.join(repo,'configs','default.toml'),
                        '--schema', os.path.join(repo,'configs','schema.json')], check=True)
    proc = subprocess.run([sys.executable, os.path.join(repo, 'tools', 'ssot_validate.py'), '--config', cfg],
                          capture_output=True, text=True)
    assert proc.returncode == 0
    assert 'OK: ssot validation passed' in proc.stdout
