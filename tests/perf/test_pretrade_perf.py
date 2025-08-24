from __future__ import annotations

import os
import time
from statistics import median

import pytest
from fastapi.testclient import TestClient

from api.service import app


def base_payload():
    return {
        "account": {"mode": "shadow"},
        "order": {"symbol": "BTCUSDT", "side": "buy", "qty": 1.0, "base_notional": 100.0},
        "market": {
            "latency_ms": 5,
            "slip_bps_est": 0.5,
            "a_bps": 10.0,
            "b_bps": 20.0,
            "score": 0.5,
            "mode_regime": "normal",
            "spread_bps": 5.0,
            "trap_cancel_deltas": [0.0, 0.0],
            "trap_add_deltas": [0.0, 0.0],
            "trap_trades_cnt": 10,
        },
        "fees_bps": 0.1,
    }


@pytest.mark.skip(reason="Perf smoke only; enable locally or in scheduled runs")
@pytest.mark.anyio
@pytest.mark.parametrize("profile, p95_target", [
    ("er_before_slip", 30.0),
    ("slip_before_er", 35.0),
])
def test_pretrade_check_p95(profile: str, p95_target: float):
    os.environ["PRETRADE_ORDER_PROFILE"] = profile
    with TestClient(app) as client:
        latencies = []
        payload = base_payload()
        # Make it pass guards to exercise full path
        payload["market"]["b_bps"] = 25.0
        payload["fees_bps"] = 0.1
        payload["market"]["slip_bps_est"] = 0.2
        for _ in range(200):
            t0 = time.perf_counter()
            r = client.post("/pretrade/check", json=payload)
            t1 = time.perf_counter()
            assert r.status_code == 200
            latencies.append((t1 - t0) * 1000.0)
        latencies.sort()
        idx = int(0.95 * (len(latencies) - 1))
        p95 = latencies[idx]
        assert p95 <= p95_target, f"p95 {p95:.2f}ms exceeds target {p95_target}ms for {profile}"
