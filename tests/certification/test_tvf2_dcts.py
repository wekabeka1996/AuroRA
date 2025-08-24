import numpy as np
from living_latent.core.certification.tvf2 import compute_dcts, quantile_grid


def test_dcts_identical_domains_high_score():
    rng = np.random.default_rng(42)
    # Source residuals ~ N(0,1)
    res_S = rng.normal(0,1,10_000)
    qhat_S = quantile_grid(res_S, alphas=(0.1,0.2,0.3,0.4))
    # Target identical distribution
    res_T = rng.normal(0,1,10_000)
    score = compute_dcts(res_T, qhat_S)
    assert 0.90 <= score <= 1.0, f"Expected high DCTS (>=0.90), got {score}"  # near perfect transfer


def test_dcts_heavier_tail_lower_score():
    rng = np.random.default_rng(123)
    res_S = rng.normal(0,1,8_000)
    qhat_S = quantile_grid(res_S, alphas=(0.1,0.2,0.3))
    # Target: mixture with occasional large variance to mimic heavier tail
    gauss = rng.normal(0,1.0,6_000)
    spikes = rng.normal(0,6.0,2_500)  # heavier tail spikes larger share
    res_T = np.concatenate([gauss, spikes])
    score = compute_dcts(res_T, qhat_S)
    assert score <= 0.88, f"Expected lower DCTS under heavier target tail, got {score}"
