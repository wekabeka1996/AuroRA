import numpy as np
from living_latent.core.icp_dynamic import AdaptiveICP


def generate_series(n=12000, phase_change_at=6000, seed=123):
    rng = np.random.default_rng(seed)
    mu = 0.0
    series = []
    ar_phi = 0.97
    drift = 0.0005
    for t in range(n):
        if t == phase_change_at:
            # regime shift: jump in mean
            mu += 0.5
        mu = ar_phi * mu + drift
        sigma = 0.02
        y = rng.normal(mu, sigma)
        # inject outliers 5%
        if rng.random() < 0.05:
            y += rng.normal(0, 0.15)
        series.append((mu, sigma, y))
    return series


def test_icp_coverage_and_outliers():
    series = generate_series()
    icp = AdaptiveICP(alpha_target=0.10, eta=0.01, window=1000, quantile_mode='p2')
    burn_in = 1000
    hits = 0
    total = 0
    miss_rates_pre = []
    miss_rates_post = []
    outlier_phase = (4000, 5000)
    for i, (mu, sigma, y) in enumerate(series):
        icp.update(y, mu, sigma)
        lo, hi = icp.predict(mu, sigma)
        if i >= burn_in:
            if lo <= y <= hi:
                hits += 1
            total += 1
        # track miss rate around outlier phase
        if outlier_phase[0] <= i < outlier_phase[0] + 300:
            miss_rates_pre.append(1 - int(lo <= y <= hi))
        if outlier_phase[1] <= i < outlier_phase[1] + 300:
            miss_rates_post.append(1 - int(lo <= y <= hi))
    empirical_cov = hits / total
    target_cov = 0.90
    assert target_cov - 0.03 <= empirical_cov <= target_cov + 0.03, f"Coverage {empirical_cov} out of tolerance"
    if miss_rates_pre and miss_rates_post:
        # Expect miss rate after adaptation to not increase
        assert np.mean(miss_rates_post) <= np.mean(miss_rates_pre) + 0.05
