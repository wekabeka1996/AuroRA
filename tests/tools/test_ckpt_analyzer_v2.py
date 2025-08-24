import torch, tempfile, json, sys, subprocess
from pathlib import Path

PY = sys.executable

def make_ckpt(p: Path, scale=1.0, noise=0.0):
    sd = {
        'layer1.weight': torch.randn(10)*scale + noise,
        'layer2.weight': torch.randn(5)*scale,
    }
    torch.save(sd, p)


def run(cmd):
    res = subprocess.run([PY]+cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def test_ckpt_analyzer_anomaly_low_cosine():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        # create reference + altered
        ref = d / 'model_ref.pt'; make_ckpt(ref, scale=1.0)
        drift = d / 'model_drift.pt'; make_ckpt(drift, scale=10.0)  # big change lowers cosine
        # Need a second file so ref becomes latest-1 and drift latest-0
        # Ensure ordering by mtime
        import time as _t; _t.sleep(0.1)
        extra = d / 'model_new.pt'; make_ckpt(extra, scale=10.0)
        jsonl = d / 'out.jsonl'
        rep = d / 'report.json'
        code, so, se = run(['tools/ckpt_analyzer_v2.py','--ckpt-dir', str(d), '--ref','latest-1','--jsonl', str(jsonl), '--report', str(rep), '--exit-on-anomaly','--profile','strict'])
        assert code == 3, f"Expected anomaly exit 3, got {code}. stderr={se}"
        assert rep.exists()
        data = json.loads(rep.read_text(encoding='utf-8'))
        assert 'analyses' in data and data['analyses']


def test_ckpt_analyzer_ok():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        ref = d / 'model_ref.pt'; make_ckpt(ref, scale=1.0)
        near = d / 'model_near.pt'; make_ckpt(near, scale=1.0)
        jsonl = d / 'out.jsonl'
        rep = d / 'report.json'
        code, so, se = run(['tools/ckpt_analyzer_v2.py','--ckpt-dir', str(d), '--ref','latest-1','--jsonl', str(jsonl), '--report', str(rep), '--profile','normal'])
        assert code == 0, se
