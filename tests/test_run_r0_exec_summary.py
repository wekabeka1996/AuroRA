import json, os, tempfile, pathlib, random
from living_latent.scripts.run_r0 import _run_single, load_profile, parse_args
from living_latent.core.icp_dynamic import AdaptiveICP

# Minimal synthetic log generator

def _make_log(dir_path: str, n: int = 20):
    p = pathlib.Path(dir_path) / 'pred_synth.jsonl'
    import math
    with open(p, 'w', encoding='utf-8') as f:
        for i in range(n):
            mu = random.uniform(-1,1)
            width = random.uniform(0.01,0.05)
            lo = mu - width/2
            hi = mu + width/2
            rec = {
                'ts': i,
                'mu': mu,
                'sigma': width/6,
                'lo': lo,
                'hi': hi,
                'latency_ms': random.uniform(10,90),
                'y': mu  # inside interval
            }
            f.write(json.dumps(rec)+'\n')
    return str(p)

def test_run_r0_exec_summary_keys():
    # Use default profile from master.yaml
    master = pathlib.Path('living_latent/cfg/master.yaml')
    prof = load_profile(master, 'default')
    with tempfile.TemporaryDirectory() as td:
        _make_log(td, 15)
        class Args:  # mimic parsed args minimal subset
            logs_dir = td
            profile = 'default'
            config = 'living_latent/cfg/master.yaml'
            seed = 123
            summary_out = os.path.join(td,'summary.json')
            calibrate = False
            grid = None
            calib_out_dir = os.path.join(td,'calib')
            top_k = 3
            objective_weights = None
            hard_constraints = None
            load_snapshot = None
            save_snapshot = None
        paths = [str(pathlib.Path(td)/'pred_synth.jsonl')]
        # _run_single now returns (metrics_out, profile_cfg, metrics_obj)
        metrics_out, _, _ = _run_single(paths, prof, Args, tweaks=None)
        # Simulate summary assembly logic
        summary = {
            'n': metrics_out['n'],
            'avg_risk_scale': metrics_out.get('avg_risk_scale'),
            'exec_block_rate': metrics_out.get('exec_block_rate'),
        }
        assert 'avg_risk_scale' in summary
        assert 'exec_block_rate' in summary
        assert summary['n'] == 15
        assert summary['avg_risk_scale'] is not None
        assert summary['exec_block_rate'] is not None
