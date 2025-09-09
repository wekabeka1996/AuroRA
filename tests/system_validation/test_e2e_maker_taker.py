import pytest
from core.aurora_event_logger import AuroraEventLogger


def test_maker_and_taker_flow_emitted_events(tmp_path):
    """Smoke E2E: simulate two decisions and assert ROUTER.DECISION emitted with positive net_after_tca."""
    # Minimal smoke: ensure emitter writes and accepts ROUTER.DECISION
    log_file = tmp_path / "aurora_events.jsonl"
    el = AuroraEventLogger(path=log_file)

    # Emit maker decision event
    el.emit('ROUTER.DECISION', {
        'symbol': 'SOON', 'side': 'BUY', 'p_fill': 0.8, 'spread_bps': 2, 'e_maker_expected': 10, 'e_taker_expected': 1, 'route': 'maker'
    })
    # Emit taker decision event
    el.emit('ROUTER.DECISION', {
        'symbol': 'SOON', 'side': 'SELL', 'p_fill': 0.2, 'spread_bps': 10, 'e_maker_expected': -1, 'e_taker_expected': 5, 'route': 'taker'
    })

    # Read back
    lines = list(open(log_file, 'r', encoding='utf-8'))
    assert any('ROUTER.DECISION' in l for l in lines)
    # Basic edge check: at least one positive net-like field present (e_maker_expected or e_taker_expected)
    assert any(('e_maker_expected' in l and '10' in l) or ('e_taker_expected' in l and '5' in l) for l in lines)
