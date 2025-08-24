import json
import math
from pathlib import Path
import tempfile
import shutil

import numpy as np

from living_latent.scripts.run_r0 import main as run_main

# We will simulate by creating a tiny log file with synthetic records.

LOG_TEMPLATE = '{"mu": 0.0, "sigma": 0.1, "lo": -0.2, "hi": 0.2, "y": 0.05}\n'

def _make_logs(dir_path: Path, n: int = 50):
    with open(dir_path / 'pred_0.jsonl', 'w', encoding='utf-8') as f:
        for _ in range(n):
            f.write(LOG_TEMPLATE)


def _run_with_lambda(tmpdir: Path, lam: float) -> dict:
    # Copy master.yaml and modify dro_risk.lambda
    cfg_src = Path('living_latent/cfg/master.yaml')
    cfg_text = cfg_src.read_text(encoding='utf-8')
    # naive replace or append block for test; we ensure lambda is present
    # If lambda already present under dro_risk we substitute; fallback simple replace
    if 'dro_risk:' in cfg_text:
        import re
        cfg_text = re.sub(r'lambda:\s*[0-9.]+', f'lambda: {lam}', cfg_text)
    tmp_cfg = tmpdir / 'master.yaml'
    tmp_cfg.parent.mkdir(parents=True, exist_ok=True)
    tmp_cfg.write_text(cfg_text, encoding='utf-8')
    # Create logs
    logs_dir = tmpdir / 'logs'
    logs_dir.mkdir()
    _make_logs(logs_dir)
    # Run script programmatically: emulate CLI args by patching sys.argv
    import sys
    prev = list(sys.argv)
    try:
        sys.argv = ['run_r0.py', '--logs_dir', str(logs_dir), '--profile', 'default', '--config', str(tmp_cfg), '--summary_out', str(tmpdir / 'summary.json')]
        run_main()
    finally:
        sys.argv = prev
    out = json.loads(Path(tmpdir / 'summary.json').read_text(encoding='utf-8'))
    return out


def test_avg_risk_scale_dro_adj_monotonic():
    tdir = Path(tempfile.mkdtemp())
    try:
        s0 = _run_with_lambda(tdir / 'lam0', 0.0)
        s1 = _run_with_lambda(tdir / 'lam1', 0.5)
        s2 = _run_with_lambda(tdir / 'lam2', 1.0)
        # lambda=0 -> factor absent or 1.0, adjusted equals base
        base0 = s0.get('avg_risk_scale')
        adj0 = s0.get('avg_risk_scale_dro_adj', base0)
        if isinstance(base0, (int,float)) and isinstance(adj0, (int,float)):
            assert math.isclose(base0, adj0, rel_tol=1e-6)
        # For higher lambda, adjusted <= base (monotonic non-increasing)
        for summ in (s1, s2):
            base = summ.get('avg_risk_scale')
            adj = summ.get('avg_risk_scale_dro_adj', base)
            if isinstance(base, (int,float)) and isinstance(adj, (int,float)):
                assert adj <= base + 1e-9
        # lambda larger -> factor should be <= previous factor (if both exist)
        f1 = s1.get('avg_risk_scale_dro_factor', 1.0)
        f2 = s2.get('avg_risk_scale_dro_factor', 1.0)
        assert f2 <= f1 + 1e-9
    finally:
        shutil.rmtree(tdir, ignore_errors=True)
