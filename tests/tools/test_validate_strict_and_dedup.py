import json
from pathlib import Path
from tools.validate_canary_logs import validate


def write_jsonl(path: Path, rows):
    with path.open('w', encoding='utf-8') as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_validate_excludes_unprogressed(tmp_path: Path):
    p = tmp_path / 'a.jsonl'
    rows = []
    # actionable intent with KELLY and ROUTER
    rows.append({"event_code": "ORDER.INTENT.RECEIVED", "details": {"intent_id": "i1"}})
    rows.append({"event_code": "KELLY.APPLIED", "details": {"intent_id": "i1"}})
    rows.append({"event_code": "ROUTER.DECISION", "details": {"intent_id": "i1", "p_fill": 0.7}})
    # unprogressed intent (only INTENT)
    rows.append({"event_code": "ORDER.INTENT.RECEIVED", "details": {"intent_id": "i2"}})
    write_jsonl(p, rows)
    thr = {
        'p95_latency_ms_max': 500,
        'deny_share_max': 1.0,
        'low_pfill_share_max': 1.0,
        'net_after_tca_median_min': 0,
        'xai_missing_rate_max': 0.01,
        'pfill_median_min': None,
        'pfill_median_max': None,
        'corrupt_rate_max': 0.01,
        'strict_progress_max': 0.6,
    }
    rc = validate(str(p), 5, thr)
    assert rc == 0  # xai_missing_rate should be 0.0 because i2 excluded

    # now set strict_progress_max below 0.5 to trigger failure (unprogressed_share = 0.5)
    thr['strict_progress_max'] = 0.1
    rc = validate(str(p), 5, thr)
    assert rc == 2


def test_validate_dedup_intents(tmp_path: Path):
    p = tmp_path / 'b.jsonl'
    rows = []
    # duplicate INTENT for same i1
    rows.append({"event_code": "ORDER.INTENT.RECEIVED", "details": {"intent_id": "i1"}})
    rows.append({"event_code": "ORDER.INTENT.RECEIVED", "details": {"intent_id": "i1"}})
    # one deny to compute deny_share correctly over unique traces (=1)
    rows.append({"event_code": "ORDER.DENY", "details": {"intent_id": "i1", "code": "EDGE_DENY"}})
    write_jsonl(p, rows)
    thr = {
        'p95_latency_ms_max': 500,
        'deny_share_max': 0.99,  # deny_share = 1.0 > 0.99 => fail
        'low_pfill_share_max': 1.0,
        'net_after_tca_median_min': 0,
        'xai_missing_rate_max': 1.0,
        'pfill_median_min': None,
        'pfill_median_max': None,
        'corrupt_rate_max': 0.01,
        'strict_progress_max': 1.0,
    }
    rc = validate(str(p), 5, thr)
    assert rc == 2  # should fail on deny_share

    # relax deny_share to 1.0 -> should pass
    thr['deny_share_max'] = 1.0
    rc = validate(str(p), 5, thr)
    assert rc == 0
