import pytest
from core.aurora_event_logger import AuroraEventLogger


def test_xai_trace_contains_required_fields(tmp_path):
    log_file = tmp_path / "aurora_events.jsonl"
    el = AuroraEventLogger(path=log_file)

    # emit full trace
    trace_id = 'trace-123'
    el.emit('ORDER.INTENT.RECEIVED', {'symbol': 'SOON', 'cid': trace_id})
    el.emit('KELLY.APPLIED', {'f_raw': 0.1, 'f_port': 0.08, 'qty_final': '1.0', 'cid': trace_id})
    el.emit('ROUTER.DECISION', {'symbol': 'SOON', 'cid': trace_id, 'e_maker_expected': 5, 'e_taker_expected': 1})
    el.emit('GOVERNANCE.TRANSITION', {'from': 'shadow', 'to': 'canary', 'cid': trace_id})

    lines = [l for l in open(log_file, 'r', encoding='utf-8')]
    # same trace id in events
    assert any(trace_id in l for l in lines)
    # KELLY.APPLIED present
    assert any('KELLY.APPLIED' in l for l in lines)
