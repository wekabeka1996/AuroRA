import json
from pathlib import Path
from tools.validate_canary_logs import validate


def test_validate_canary_logs_smoke(tmp_path):
    p = tmp_path / 'aurora_events.jsonl'
    events = [
        { 'event_code': 'ORDER.INTENT.RECEIVED', 'details': {'intent_id':'i1'} },
        { 'event_code': 'ORDER.INTENT.RECEIVED', 'details': {'intent_id':'i2'} },
        { 'event_code': 'KELLY.APPLIED', 'details': {'intent_id':'i1', 'qty_final':'1'} },
        { 'event_code': 'ROUTER.DECISION', 'details': {'intent_id':'i1', 'p_fill':0.8, 'net_after_tca': 10 } },
        { 'event_code': 'ORDER.DENY', 'details': {'intent_id':'i2', 'code':'LOW_PFILL.DENY'} }
    ]
    with p.open('w', encoding='utf-8') as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + '\n')

    rc = validate(str(p), window_mins=5, thresholds={
        'p95_latency_ms_max': 500.0,
        'deny_share_max': 0.9,
        'low_pfill_share_max': 0.9,
        'net_after_tca_median_min': 0,
        'xai_missing_rate_max': 0.5,
    })
    assert rc == 0
