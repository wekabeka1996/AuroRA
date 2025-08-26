from __future__ import annotations

from core.lifecycle_correlation import LifecycleCorrelator


def test_correlation_submit_ack_fill_and_percentiles():
    lc = LifecycleCorrelator(window_s=60)
    base = 1_000_000_000_000
    # Order A: submit -> ack 100ms, ack -> fill 200ms
    lc.add_event({"cid": "A", "type": "ORDER.SUBMIT", "ts_ns": base})
    lc.add_event({"cid": "A", "type": "ORDER.ACK", "ts_ns": base + 100_000_000})
    lc.add_event({"cid": "A", "type": "ORDER.FILL", "ts_ns": base + 300_000_000})
    # Order B: submit -> ack 200ms, ack -> cancel 400ms
    lc.add_event({"cid": "B", "type": "ORDER.SUBMIT", "ts_ns": base})
    lc.add_event({"cid": "B", "type": "ORDER.ACK", "ts_ns": base + 200_000_000})
    lc.add_event({"cid": "B", "type": "ORDER.CANCEL", "ts_ns": base + 600_000_000})
    res = lc.finalize(now_ns=base + 10_000_000_000)
    sa = res["latency_ms"]["submit_ack"]
    ad = res["latency_ms"]["ack_done"]
    assert sa["p50"] == 150.0 or sa["p50"] == 100.0  # nearest-rank on 2 samples (100,200)
    assert ad["p50"] in (200.0, 400.0)
    assert res["orders"]["A"]["final"] == "FILLED"
    assert res["orders"]["B"]["final"] == "CANCELED"


def test_expire_when_no_ack_within_window():
    lc = LifecycleCorrelator(window_s=1)  # 1s window
    base = 2_000_000_000_000
    lc.add_event({"cid": "X", "type": "ORDER.SUBMIT", "ts_ns": base})
    res = lc.finalize(now_ns=base + 2_100_000_000)  # >1s later
    assert res["orders"]["X"]["final"] == "EXPIRED"


def test_partial_and_fill_merge_and_qty_accumulation():
    lc = LifecycleCorrelator(window_s=60)
    t0 = 3_000_000_000_000
    lc.add_event({"cid": "C", "type": "ORDER.SUBMIT", "ts_ns": t0})
    lc.add_event({"cid": "C", "type": "ORDER.ACK", "ts_ns": t0 + 50_000_000})
    lc.add_event({"cid": "C", "type": "ORDER.PARTIAL", "ts_ns": t0 + 100_000_000, "fill_qty": 0.2})
    lc.add_event({"cid": "C", "type": "ORDER.PARTIAL", "ts_ns": t0 + 150_000_000, "fill_qty": 0.3})
    lc.add_event({"cid": "C", "type": "ORDER.FILL", "ts_ns": t0 + 200_000_000, "fill_qty": 0.5})
    res = lc.finalize(now_ns=t0 + 1_000_000_000)
    oc = res["orders"]["C"]
    assert oc["final"] == "FILLED"
    assert oc["fills"] == 3
    assert abs(oc["qty_filled"] - 1.0) < 1e-6
