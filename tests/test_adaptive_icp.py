import math
import numpy as np
from living_latent.core.icp_dynamic import AdaptiveICP


def generate_stream(n=3000, drift=False, seed=123):
    rng = np.random.default_rng(seed)
    mu = 0.0
    for i in range(n):
        sigma = 1.0
        if drift and i > n//2:
            mu = 0.5  # mean shift
        y = rng.normal(mu, sigma)
        yield y, mu, sigma


def test_adaptive_icp_convergence():
    icp = AdaptiveICP(alpha_target=0.1, eta=0.02, window=1000, quantile_mode='p2')
    hits = 0
    total = 0
    for y, mu, sigma in generate_stream():
        lo, hi = icp.predict(mu, sigma)
        if lo <= y <= hi:
            hits += 1
        total += 1
        icp.update(y, mu, sigma)
    empirical_cov = hits / total
    # Expect coverage within 0.03 absolute of 0.9 target after warmup
    assert abs(empirical_cov - (1 - icp.alpha_target)) <= 0.03, f"coverage {empirical_cov:.4f} diverged from target"
    st = icp.stats()
    assert math.isfinite(st.q_estimate) or len(icp.scores) < 100, "q_estimate should be finite after warmup"


def test_adaptive_icp_transition_resilience():
    icp = AdaptiveICP(alpha_target=0.1, eta=0.02, window=1000, quantile_mode='p2')
    hits = 0
    total = 0
    for y, mu, sigma in generate_stream(drift=True):
        lo, hi = icp.predict(mu, sigma)
        if lo <= y <= hi:
            hits += 1
        total += 1
        icp.update(y, mu, sigma)
    empirical_cov = hits / total
    # Allow slightly larger deviation under drift but still bounded
    assert abs(empirical_cov - (1 - icp.alpha_target)) <= 0.05, f"coverage {empirical_cov:.4f} deviated under drift"
