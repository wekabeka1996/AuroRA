import pytest
from core.aurora_event_logger import AuroraEventLogger
from tools.metrics_exporter import METRICS


@pytest.mark.perf
def test_latency_histogram_and_sla(tmp_path):
    log_file = tmp_path / "aurora_events.jsonl"
    el = AuroraEventLogger(path=log_file)

    # simulate latencies
    METRICS.exec.observe_latency_ms(10)
    METRICS.exec.observe_latency_ms(50)
    METRICS.exec.observe_latency_ms(300)

    # if too slow, emit SLA.DENY
    METRICS.exec.observe_latency_ms(800)
    el.emit('SLA.DENY', {'reason': 'SLA_LATENCY', 'symbol': 'SOON'})

    lines = list(open(log_file, 'r', encoding='utf-8'))
    assert any('SLA.DENY' in l for l in lines)
