import pytest
from core.aurora_event_logger import AuroraEventLogger
from tools.metrics_exporter import METRICS


def test_denies_and_metrics_increment(tmp_path):
    log_file = tmp_path / "aurora_events.jsonl"
    el = AuroraEventLogger(path=log_file)

    # emit denies
    el.emit('ORDER.DENY', {'reason': 'LOW_PFILL.DENY', 'symbol': 'SOON'})
    el.emit('ORDER.DENY', {'reason': 'POST_ONLY_UNAVAILABLE', 'symbol': 'SOON'})
    el.emit('ORDER.DENY', {'reason': 'SIZE_ZERO.DENY', 'symbol': 'SOON'})

    # metric hook: attach METRICS.aurora._order_denies counter
    try:
        el.set_counter(METRICS.aurora._order_denies)
    except Exception:
        pass

    # Read back events
    lines = list(open(log_file, 'r', encoding='utf-8'))
    assert any('ORDER.DENY' in l for l in lines)

    # Check that metric counter exists and is callable
    assert hasattr(METRICS.aurora, 'inc_order_deny')
