import tempfile, yaml, json, sys, subprocess
from pathlib import Path

PY = sys.executable

CURRENT = {
  'thresholds': {'dcts_min': 0.9, 'max_churn_per_1k': 15.0},
  'hard_meta': {'dcts_min': {'hard_enabled': True}}
}
RATCHET = {
  'thresholds': {'dcts_min': 0.905, 'max_churn_per_1k': 14.5},
  'hard_meta': {'dcts_min': {'hard_enabled': True}}
}
DECISIONS = [
  {'metric':'tvf2.dcts_robust','threshold_key':'dcts_min','enable':True,'changed':True,'reasons':['n>=20','warn_rate<=0.05','delta_p95p10<=0.07','var_ratio<=0.85'],'stats':{'n':25,'warn_rate':0.0,'delta_p95_p10':0.01}},
  {'metric':'ci.churn','threshold_key':'max_churn_per_1k','enable':True,'changed':True,'reasons':['n>=20','warn_rate<=0.05','delta_p95p10<=0.07','var_ratio<=0.85'],'stats':{'n':25,'warn_rate':0.0,'delta_p95_p10':0.5}}
]


def run(cmd):
    res = subprocess.run([PY] + cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def test_pr_bundle_sections():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        cur = d / 'cur.yaml'; cur.write_text(yaml.safe_dump(CURRENT), encoding='utf-8')
        rat = d / 'rat.yaml'; rat.write_text(yaml.safe_dump(RATCHET), encoding='utf-8')
        hard = d / 'hard.jsonl'; hard.write_text('\n'.join(json.dumps(x) for x in DECISIONS), encoding='utf-8')
        audit_md = d / 'audit.md'; audit_md.write_text('# Audit\nvar_ratio: 0.8', encoding='utf-8')
        out = d / 'summary.md'
        code, so, se = run(['tools/ci_pr_bundle.py','--current', str(cur), '--ratchet', str(rat), '--hard-log', str(hard), '--audit-md', str(audit_md), '--out', str(out)])
        assert code == 0, se + so
        md = out.read_text(encoding='utf-8')
        for h in ["Overview","Ratchet Diff","Hard-enable Decisions","DCTS Audit","Rollback Playbook"]:
            assert f"## {h}" in md
        assert '| dcts_min |' in md  # diff row
