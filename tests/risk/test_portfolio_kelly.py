from __future__ import annotations
import numpy as np
from core.risk.portfolio_kelly import ledoit_wolf_shrink, compute_portfolio_fraction


def test_ledoit_wolf_delta_bounds_and_psd():
    # Random symmetric positive matrix (not guaranteed PSD)
    rng = np.random.default_rng(123)
    A = rng.normal(size=(5,5))
    S = (A + A.T) / 2.0
    S_hat, delta = ledoit_wolf_shrink(S)
    # delta in [0,1]
    assert 0.0 <= delta <= 1.0
    # S_hat should be symmetric and numerically PSD (min eig >= -1e-8)
    evals = np.linalg.eigvalsh((S_hat + S_hat.T)/2.0)
    assert evals.min() >= -1e-8


def test_compute_portfolio_fraction_monotone_with_variance():
    # Two-asset case: higher variance should reduce f_port
    cov_low = np.array([[0.01, 0.0],[0.0, 0.01]])
    cov_high = np.array([[0.10, 0.08],[0.08, 0.10]])
    w = np.array([0.5, 0.5])
    f_raw = 0.02
    f_max = 0.05
    f_low = compute_portfolio_fraction(f_raw, ["A","B"], w, cov_low, f_max)
    f_high = compute_portfolio_fraction(f_raw, ["A","B"], w, cov_high, f_max)
    assert f_high <= f_low + 1e-12
