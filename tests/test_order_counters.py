from __future__ import annotations

import importlib

from fastapi.testclient import TestClient


def get_metric_value(text: str, metric: str) -> float:
    for line in text.splitlines():
        if line.startswith(metric):
            try:
                return float(line.split()[-1])
            except Exception:
                return 0.0
    return 0.0


def test_orders_counters_increment_on_log_writes(tmp_path):
    svc = importlib.import_module("api.service")
    app = svc.app
    client = TestClient(app)

    # Set OPS token for protected endpoints used elsewhere
    app.state.ops_token = "t" * 32

    # Baseline metrics
    before = client.get("/metrics").text
    b_filled = get_metric_value(before, "aurora_orders_success_total")
    b_denied = get_metric_value(before, "aurora_orders_denied_total")
    b_rejected = get_metric_value(before, "aurora_orders_rejected_total")

    # 1) Deny in pretrade via extreme spread_bps
    pre_body = {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "LONG", "qty": 0.01, "price": 100.0, "base_notional": 1.0},
        "market": {"spread_bps": 1000.0, "latency_ms": 1.0, "score": 0.0, "a_bps": 10.0, "b_bps": 10.0},
        "fees_bps": 1.0,
    }
    client.post("/pretrade/check", json=pre_body)

    # 2) Success in posttrade
    post_success = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "qty": 0.01,
        "price": 100.0,
        "status": "filled",
        "filled": 0.01,
        "average": 100.0,
        "order_id": "ok1",
    }
    client.post("/posttrade/log", json=post_success)

    # 3) Reject in posttrade
    post_reject = {
        "symbol": "BTCUSDT",
        "side": "LONG",
        "qty": 0.01,
        "price": 100.0,
        "status": "rejected",
        "error_code": "EXCHANGE_ERROR",
        "error_msg": "something",
        "order_id": "rej1",
    }
    client.post("/posttrade/log", json=post_reject)

    after = client.get("/metrics").text
    a_filled = get_metric_value(after, "aurora_orders_success_total")
    a_denied = get_metric_value(after, "aurora_orders_denied_total")
    a_rejected = get_metric_value(after, "aurora_orders_rejected_total")

    assert a_filled == b_filled + 1
    assert a_denied == b_denied + 1
    assert a_rejected == b_rejected + 1
