import subprocess
from pathlib import Path


def _run_seed(out, seed):
    cmd = ['python', 'tools/seed_synthetic_flow.py', '--out', str(out), '--seed', str(seed), '--scenarios', 'maker,taker,low_pfill,size_zero,sla_deny', '--n', '1']
    subprocess.check_call(cmd)


def test_seed_synthetic_flow_determinism(tmp_path):
    f1 = tmp_path / 'a.jsonl'
    f2 = tmp_path / 'b.jsonl'
    _run_seed(f1, 123)
    _run_seed(f2, 123)
    b1 = f1.read_bytes()
    b2 = f2.read_bytes()
    assert b1 == b2
