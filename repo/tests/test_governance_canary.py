from repo.core.governance.canary import Canary

NS = 1_000_000_000


def test_canary_triggers_decision_alerts_and_cvar():
    c = Canary()

    # First decision: 'deny' with poor calibration (p high but y=0)
    c.on_decision(ts_ns=0, action='deny', p=0.99, y=0)
    alerts1 = c.poll()
    # Should include at least NoTrades, DenySpike, and CalibrationDrift alerts
    msgs = " ".join(a.message for a in alerts1)
    assert any("NoTrades" in a.message for a in alerts1)
    assert any("DenySpike" in a.message for a in alerts1)
    assert any("CalibrationDrift" in a.message for a in alerts1)

    # Now feed returns to trigger CVaR breach (many losses) spaced > debounce interval
    ts = 0
    for _ in range(60):
        ts += 61 * NS  # 61s to pass debounce windows
        c.on_return(ts_ns=ts, ret=-0.05)
    alerts2 = c.poll()
    assert any("CvarBreachAlert" in a.message for a in alerts2)
