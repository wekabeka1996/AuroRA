import math
import numpy as np

from living_latent.core.icp_dynamic import AdaptiveICP
from living_latent.core.icp_adapter import ICPAdapter


def simulate_series(n=5000, drift=0.0, sigma=1.0, shock_every=700):
    rng = np.random.default_rng(1337)
    y = []
    x = 0.0
    for i in range(n):
        if shock_every and i % shock_every == 0 and i > 0:
            x += rng.normal(0, 5*sigma)
        x += drift + rng.normal(0, sigma)
        y.append(x)
    return np.array(y)


def test_adaptive_icp_adapter_migration():
    series = simulate_series()
    icp_core = AdaptiveICP(alpha_target=0.1, eta=0.01, window=1000, quantile_mode='p2')
    icp = ICPAdapter(icp_core)

    misses = 0
    burn_in = 400
    alphas = []
    for i in range(1, len(series)):
        mu = series[i-1]  # naive one-step hold forecast
        sigma = 1.0  # pretend scale
        lo, hi = icp.predict(mu, sigma)
        y = series[i]
        miss = not (lo <= y <= hi)
        misses += int(miss)
        icp.update(y, mu, sigma)
        if icp_core.stats().count > burn_in:
            alphas.append(icp_core.alpha)

    stats = icp_core.stats()
    empirical_coverage = 1 - misses / (len(series)-1)

    # After burn-in, alpha should not collapse to extremes
    assert 0.02 < stats.alpha < 0.3, f"Alpha out of sane range: {stats.alpha}"

    # Coverage near target within tolerance
    assert abs(empirical_coverage - (1 - icp_core.alpha_target)) < 0.03, (
        f"Coverage {empirical_coverage:.3f} deviates from target {(1-icp_core.alpha_target):.3f}"
    )

    # Alpha should exhibit adaptation (some variance)
    if len(alphas) > 10:
        var_alpha = float(np.var(alphas))
        assert var_alpha > 1e-5, "Alpha variance too low; adaptation seems inert"

    # q estimate finite
    assert math.isfinite(stats.q_estimate) and stats.q_estimate > 0
