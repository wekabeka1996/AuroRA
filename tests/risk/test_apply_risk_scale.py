from living_latent.execution.gating import apply_risk_scale

def test_apply_risk_scale_basic():
    assert apply_risk_scale(100.0, 0.25) == 25.0
    assert apply_risk_scale(50, 1.5) == 50.0  # clipped to 1.0
    assert apply_risk_scale(50, -0.2) == 0.0  # negative -> 0
    out = apply_risk_scale(123, 0.3333)
    assert isinstance(out, float)


def test_apply_risk_scale_edgecases():
    assert apply_risk_scale(0, 0.5) == 0.0
    assert apply_risk_scale(100, 0.0) == 0.0
