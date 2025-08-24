import json, os, sys, tempfile, math, yaml, subprocess, time
from pathlib import Path

PY = sys.executable

def write_summary(dir_path: Path, idx: int, coverage=0.91, dcts_robust=0.95, churn=20.0):
    # minimal summary fields consumed by derive_ci_thresholds
    payload = {
        'coverage_empirical': coverage,
        'decision_churn_per_1k': churn,
        'tvf2': {
            'dcts_robust': {'value': dcts_robust},
        }
    }
    (dir_path / f'summary_{idx:03d}.json').write_text(json.dumps(payload), encoding='utf-8')


def make_audit_json(path: Path, var_ratio=0.80, robust_n=25):
    audit = {
        'var_ratio': var_ratio,
        'counts': {'robust': robust_n}
    }
    path.write_text(json.dumps(audit), encoding='utf-8')


def run(cmd):
    res = subprocess.run([PY] + cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def test_e2e_chain_hard_fail_and_pass():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        summaries_dir = d / 'summaries'; summaries_dir.mkdir()
        # Generate >=25 summaries (fresh enough) stable metrics
        for i in range(25):
            write_summary(summaries_dir, i, coverage=0.91 + 0.001*(i%3), dcts_robust=0.95 - 0.002*(i%5), churn=18.0 + 0.2*(i%4))
        audit_path = d / 'dcts_audit.json'
        make_audit_json(audit_path, var_ratio=0.82, robust_n=25)
        out_yaml = d / 'ci_thresholds.yaml'
        report_json = d / 'report.json'
        # Derive with hard candidates and enable hard for dcts + churn
        code, so, se = run(['scripts/derive_ci_thresholds.py', '--summaries', str(summaries_dir), '--out', str(out_yaml), '--report', str(report_json), '--emit-hard-candidates', '--enable-hard', 'tvf2.dcts,ci.churn', '--dcts-audit-json', str(audit_path), '--force'])
        assert code in (0,2), se + so
        derived = yaml.safe_load(out_yaml.read_text(encoding='utf-8'))
        # Ensure hard_meta exists for dcts_min and max_churn_per_1k
        hm = derived.get('hard_meta', {})
        assert 'dcts_min' in hm and hm['dcts_min'].get('hard_enabled') is True
        assert 'max_churn_per_1k' in hm and hm['max_churn_per_1k'].get('hard_enabled') is True
        # Ratchet dryrun (should not alter drastically)
        ratchet_out = d / 'ci_thresholds.ratchet.yaml'
        code_r, so_r, se_r = run(['tools/ci_ratchet.py','--current', str(out_yaml), '--proposal', str(report_json), '--out', str(ratchet_out), '--max-step','0.05','--dryrun'])
        assert code_r == 2, so_r + se_r
        ratchet_yaml = yaml.safe_load(ratchet_out.read_text(encoding='utf-8'))
        # Simulate gating for PASS scenario (values within thresholds)
        from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
        ci_cfg = {'hard_enabled': True, 'enter_warn_runs': 1, 'exit_warn_runs': 1}
        specs = [
            MetricSpec(name='churn', source_key='decision_churn_per_1k', threshold_key='max_churn_per_1k', relation='<=', hard_candidate=True),
            MetricSpec(name='dcts', source_key='tvf2.dcts_robust_value', threshold_key='dcts_min', relation='>=', hard_candidate=True)
        ]
        sm = CIGatingStateMachine(ci_cfg, specs)
        summary_good = {
            'decision_churn_per_1k': derived['thresholds']['max_churn_per_1k'] - 1.0,
            'tvf2.dcts_robust_value': derived['thresholds']['dcts_min'] + 0.01
        }
        # flatten thresholds for gating (simulate structure gating expects)
        thresholds_flat = {**derived['thresholds'], 'hard_meta': derived.get('hard_meta', {})}
        events_good = sm.evaluate_batch('run_ok', summary_good, thresholds_flat)
        assert not sm.any_hard_failure(events_good)
        # Now FAIL scenario: churn exceeds +10 and dcts below min
        summary_bad = {
            'decision_churn_per_1k': derived['thresholds']['max_churn_per_1k'] + 5.0,
            'tvf2.dcts_robust_value': derived['thresholds']['dcts_min'] - 0.05
        }
        events_bad = sm.evaluate_batch('run_bad', summary_bad, thresholds_flat)
        assert sm.any_hard_failure(events_bad)
        # Ensure at least one HARD log message present
        hard_msgs = [e.message for e in events_bad if '[CI-GATING][HARD]' in e.message]
        assert hard_msgs, 'Expected HARD events not found'
