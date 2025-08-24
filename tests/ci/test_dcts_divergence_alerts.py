from pathlib import Path


def test_dcts_divergence_alert_triggers(tmp_path):
    from living_latent.core.ci.dcts_divergence import DCTSDivergenceConfig, DCTSDivergenceMonitor
    # Configure small thresholds to trigger breaches quickly
    cfg = DCTSDivergenceConfig(enabled=True, abs_delta_max=0.002, rel_delta_max=0.002, window_runs=3, min_breaches=2, persistence_file=tmp_path/ 'div.json')
    mon = DCTSDivergenceMonitor(cfg)
    # First observation (delta 0.003) -> breach
    r1 = mon.observe(0.900, 0.903)
    assert r1 is not None and r1['breach'] is True
    # Second observation (delta 0.0005) -> no breach
    r2 = mon.observe(0.902, 0.9025)
    assert r2 is not None and r2['breach'] is False
    # Third observation (delta 0.0035) -> breach; should alert because 2 breaches within window_runs=3 and min_breaches=2
    r3 = mon.observe(0.904, 0.9075)
    assert r3 is not None and r3['breach'] is True
    assert mon.should_alert() is True
