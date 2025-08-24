import json, os, tempfile, shutil
from pathlib import Path
import yaml
import subprocess, sys

RATCHET = Path('tools/ci_ratchet.py')

CURR = {
  'surprisal_p95_max': 2.0,
  'latency': {'p95_ms_max': 120.0},
  'nested': {'deep': {'a': 100}}
}
PROP = {
  'surprisal_p95_max': 1.6,  # 20% tighter -> clamp to 5%
  'latency': {'p95_ms_max': 110.0},  # ~8% tighter -> clamp
  'nested': {'deep': {'a': 50}},  # 50% decrease -> clamp
  'new_metric': 42.0
}


def run_tool(curr_path, prop_path, out_path, report_path, max_step=0.05):
    cmd = [sys.executable, str(RATCHET), '--current', str(curr_path), '--proposed', str(prop_path), '--out', str(out_path), '--report', str(report_path), '--max-step', str(max_step)]
    cp = subprocess.run(cmd, capture_output=True, text=True)
    assert cp.returncode == 0, cp.stderr
    return cp


def test_ratchet_clamps_and_reports(tmp_path):
    curr = tmp_path / 'curr.yaml'
    prop = tmp_path / 'prop.yaml'
    outp = tmp_path / 'out.yaml'
    rep = tmp_path / 'rep.json'
    with open(curr,'w',encoding='utf-8') as f:
        yaml.safe_dump(CURR, f)
    with open(prop,'w',encoding='utf-8') as f:
        yaml.safe_dump(PROP, f)
    run_tool(curr, prop, outp, rep)
    out = yaml.safe_load(outp.read_text(encoding='utf-8'))
    report = json.loads(rep.read_text(encoding='utf-8'))
    # surp: old 2.0 -> target 1.6 (20% delta) => clamp to 2.0*(1-0.05)=1.9
    assert abs(out['surprisal_p95_max'] - 1.9) < 1e-9
    # latency: 120->110 (~8.33%) clamp to 120*(1-0.05) = 114
    assert abs(out['latency']['p95_ms_max'] - 114.0) < 1e-9
    # nested: 100->50 (50%) clamp to 95
    assert abs(out['nested']['deep']['a'] - 95.0) < 1e-9
    # new metric introduced untouched
    assert out['new_metric'] == 42.0
    assert report['clamped_total'] == 3
    assert 'surprisal_p95_max' in report['clamped']
    assert 'latency.p95_ms_max' in report['clamped']
    assert 'nested.deep.a' in report['clamped']
