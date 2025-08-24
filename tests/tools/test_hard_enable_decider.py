import json, tempfile, yaml, sys, subprocess
from pathlib import Path

PY = sys.executable

SAMPLE_LOG_LINE = lambda val, state='OK': json.dumps({
    'run_id': 'r',
    'metrics': {
        'tvf2.dcts_robust': {'value': val, 'state': state},
        'ci.churn': {'value': 10.0, 'state': state},
    }
})

AUDIT = {'var_ratio': 0.8, 'counts': {'robust': 30}}

BASE_THRESHOLDS = {
  'thresholds': {
    'dcts_min': 0.9,
    'max_churn_per_1k': 15.0
  },
  'hard_meta': {}
}

def run(cmd):
    res = subprocess.run([PY] + cmd, capture_output=True, text=True)
    return res.returncode, res.stdout, res.stderr


def test_decider_enables_when_all_good():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        logp = d / 'gating.jsonl'
        with logp.open('w', encoding='utf-8') as f:
            for i in range(25):
                f.write(SAMPLE_LOG_LINE(0.95 + 0.0005*i) + '\n')
        auditp = d / 'audit.json'
        auditp.write_text(json.dumps(AUDIT), encoding='utf-8')
        thp = d / 'ci_thresholds.yaml'
        thp.write_text(yaml.safe_dump(BASE_THRESHOLDS), encoding='utf-8')
        outp = d / 'out.yaml'
        dec_log = d / 'decisions.jsonl'
        code, so, se = run(['tools/hard_enable_decider.py','--gating-log', str(logp), '--audit-json', str(auditp), '--thresholds', str(thp), '--out', str(outp), '--decision-log', str(dec_log), '--dryrun'])
        assert code == 2, se + so
        updated = yaml.safe_load(outp.read_text(encoding='utf-8'))
        assert 'dcts_min' in updated['hard_meta'] and updated['hard_meta']['dcts_min']['hard_enabled'] is True
        assert 'max_churn_per_1k' in updated['hard_meta'] and updated['hard_meta']['max_churn_per_1k']['hard_enabled'] is True
        # decision log lines present
        lines = dec_log.read_text(encoding='utf-8').strip().splitlines()
        assert len(lines) >= 2


def test_decider_respects_warn_rate():
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        logp = d / 'gating.jsonl'
        with logp.open('w', encoding='utf-8') as f:
            for i in range(25):
                state = 'WARN' if i < 10 else 'OK'
                f.write(SAMPLE_LOG_LINE(0.95, state=state) + '\n')
        auditp = d / 'audit.json'
        auditp.write_text(json.dumps(AUDIT), encoding='utf-8')
        thp = d / 'ci_thresholds.yaml'
        thp.write_text(yaml.safe_dump(BASE_THRESHOLDS), encoding='utf-8')
        outp = d / 'out.yaml'
        code, so, se = run(['tools/hard_enable_decider.py','--gating-log', str(logp), '--audit-json', str(auditp), '--thresholds', str(thp), '--out', str(outp), '--max-warn-rate','0.05','--dryrun'])
        assert code == 2
        updated = yaml.safe_load(outp.read_text(encoding='utf-8'))
        # should NOT enable due to high warn rate
        assert updated['hard_meta'].get('dcts_min', {}).get('hard_enabled') is not True


def test_hard_meta_backcompat():
    """Test that hard_meta schema normalization works with legacy data."""
    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        logp = d / 'gating.jsonl'
        with logp.open('w', encoding='utf-8') as f:
            for i in range(25):
                f.write(SAMPLE_LOG_LINE(0.95 + 0.0005*i) + '\n')
        auditp = d / 'audit.json'
        auditp.write_text(json.dumps(AUDIT), encoding='utf-8')
        
        # Legacy schema with old field names
        legacy_thresholds = {
            'thresholds': {
                'dcts_min': 0.9,
                'max_churn_per_1k': 15.0
            },
            'hard_meta': {
                'dcts_min': {
                    'hard_enabled': True,
                    'hard_candidate_reasons': ['legacy_reason']  # Old field name
                }
            }
        }
        thp = d / 'ci_thresholds.yaml'
        thp.write_text(yaml.safe_dump(legacy_thresholds), encoding='utf-8')
        outp = d / 'out.yaml'
        dec_log = d / 'decisions.jsonl'
        
        code, so, se = run(['tools/hard_enable_decider.py','--gating-log', str(logp), '--audit-json', str(auditp), '--thresholds', str(thp), '--out', str(outp), '--decision-log', str(dec_log), '--dryrun'])
        assert code == 2, se + so
        
        updated = yaml.safe_load(outp.read_text(encoding='utf-8'))
        
        # Should have updated schema v1 with all required fields
        assert 'dcts_min' in updated['hard_meta'], "Should have dcts_min in hard_meta"
        meta = updated['hard_meta']['dcts_min']
        assert meta['schema_version'] == 1, "Should have schema_version=1"
        assert 'reasons' in meta, "Should have reasons field"
        assert 'decided_by' in meta, "Should have decided_by field"
        assert 'timestamp' in meta, "Should have timestamp field"
        assert 'window_n' in meta, "Should have window_n field"
        assert meta['hard_enabled'] is True, "Should keep hard_enabled=True"
