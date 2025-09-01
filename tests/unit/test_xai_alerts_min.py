import pytest

alerts = pytest.importorskip("core.xai.alerts", reason="xai alerts missing")


def test_basic_why_codes():
    r = alerts.route_reason_for_context
    # Call with synthetic contexts
    assert isinstance(r({"latency_ms": 9999}), str)

