import pytest
from core.aurora_event_logger import AuroraEventLogger


def test_governance_transitions_and_alpha(tmp_path):
    log_file = tmp_path / "aurora_events.jsonl"
    el = AuroraEventLogger(path=log_file)

    # shadow -> canary
    el.emit('GOVERNANCE.TRANSITION', {'from': 'shadow', 'to': 'canary', 'reason': 'promo_request'})
    el.emit('ALPHA.LEDGER.UPDATE', {'delta': 0.01, 'symbol': 'SOON'})

    # canary -> live
    el.emit('GOVERNANCE.TRANSITION', {'from': 'canary', 'to': 'live', 'reason': 'soak_ok'})
    el.emit('ALPHA.LEDGER.UPDATE', {'delta': 0.02, 'symbol': 'SOON'})

    lines = list(open(log_file, 'r', encoding='utf-8'))
    assert any('GOVERNANCE.TRANSITION' in l for l in lines)
    assert any('ALPHA.LEDGER.UPDATE' in l for l in lines)
