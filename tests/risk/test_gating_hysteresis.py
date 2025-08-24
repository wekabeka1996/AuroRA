import math

from living_latent.execution.gating import DecisionHysteresis, DwellConfig

def test_hysteresis_transitions_and_churn():
    cfg = DwellConfig(min_dwell_pass=2, min_dwell_derisk=2)
    dh = DecisionHysteresis(cfg)
    proposals = ["DERISK", "DERISK", "DERISK", "PASS", "PASS", "PASS"]
    results = [dh.update(p) for p in proposals]
    # Expect two transitions: PASS->DERISK (after satisfying dwell), DERISK->PASS
    assert dh.transitions == 2, f"Expected 2 transitions got {dh.transitions}"
    assert results[0] == "PASS"
    assert results[2] == "DERISK"  # transition point
    assert results[-1] == "PASS"
    expected_churn = 1000.0 * dh.transitions / dh.decisions
    assert math.isclose(dh.churn_per_1k(), expected_churn, rel_tol=1e-9)

def test_hysteresis_no_transition_if_not_enough_dwell():
    cfg = DwellConfig(min_dwell_pass=5, min_dwell_derisk=5)
    dh = DecisionHysteresis(cfg)
    for _ in range(3):
        s = dh.update("DERISK")
        assert s == "PASS"
    assert dh.transitions == 0
