from core.execution.sla import SLAMonitor


def test_sla_monitor_quantiles_and_gate():
    sla = SLAMonitor(window=1000, kappa_bps_per_ms=0.1, edge_floor_bps=1.0, max_latency_ms=25.0)

    # Observe some latencies (ms)
    samples = [5, 7, 8, 10, 12, 14, 15, 20, 21, 22]
    for x in samples:
        sla.observe(x)

    s = sla.summary()
    # Basic sanity on quantiles
    assert s.count == len(samples)
    assert 10 <= s.p50_ms <= 16  # median in range
    assert s.p90_ms >= s.p50_ms and s.p99_ms >= s.p90_ms

    # Gate allow: E_after = 10 - 0.1*15 = 8.5 > edge_floor (1.0), latency within SLA
    res_ok = sla.check(edge_bps=10.0, latency_ms=15.0)
    assert res_ok.allow is True and res_ok.edge_after_bps > 1.0

    # Gate deny by edge floor: E_after = 3 - 0.1*20 = 1.0 (== floor) -> still allow (strict < floor denies)
    res_eq = sla.check(edge_bps=3.0, latency_ms=20.0)
    assert res_eq.allow is True

    # Gate deny by edge: E_after = 3 - 0.1*25 = 0.5 < 1.0
    res_low = sla.check(edge_bps=3.0, latency_ms=25.0)
    assert res_low.allow is False and "Edge after latency" in res_low.reason

    # Gate deny by SLA latency
    res_sla = sla.check(edge_bps=100.0, latency_ms=30.0)
    assert res_sla.allow is False and "SLA:" in res_sla.reason
