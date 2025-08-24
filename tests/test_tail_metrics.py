import numpy as np
from living_latent.core.tail_metrics import hill_tail_index, extremal_index_runs, upper_tail_dependence, InsufficientTailSamples
import pytest

def test_hill_tail_index_basic():
    # Generate Pareto( alpha ) with tail index xi = 1/alpha ; choose alpha=3 -> xi ~= 0.333
    rng = np.random.default_rng(0)
    alpha = 3.0
    n = 5000
    # Pareto: X = U^{-1/alpha}
    U = rng.uniform(size=n)
    X = (U ** (-1/alpha))
    res = hill_tail_index(X, k=None, min_k=10)
    assert res.k > 0
    assert 0.15 < res.xi < 0.6  # loose bounds


def test_extremal_index_runs():
    rng = np.random.default_rng(1)
    # IID normal -> extremal index ~1
    x = rng.standard_normal(2000)
    theta = extremal_index_runs(x, threshold_q=0.98)
    assert 0.6 < theta <= 1.05


def test_upper_tail_dependence():
    rng = np.random.default_rng(2)
    # Construct dependent heavy tails: Y = X + noise
    X = rng.standard_t(df=5, size=4000)
    Y = X + 0.2 * rng.standard_t(df=5, size=4000)
    lam = upper_tail_dependence(X, Y, threshold_q=0.95)
    assert lam > 0.2  # should show some dependence


def test_extremal_index_clustering():
    # AR(1) with strong positive autocorrelation should yield theta_e < 1
    rng = np.random.default_rng(42)
    n = 5000
    phi = 0.8
    eps = rng.standard_normal(n)
    x = np.zeros(n)
    for t in range(1, n):
        x[t] = phi * x[t-1] + eps[t]
    theta = extremal_index_runs(x, threshold_q=0.95)
    assert theta < 0.9  # clustered extremes reduce extremal index


def test_upper_tail_independence():
    # Independent Pareto samples => tail dependence ~0
    rng = np.random.default_rng(7)
    n = 6000
    alpha = 3.0
    U1 = rng.uniform(size=n)
    U2 = rng.uniform(size=n)
    X = U1 ** (-1/alpha)
    Y = U2 ** (-1/alpha)
    lam = upper_tail_dependence(X, Y, threshold_q=0.97)
    assert lam < 0.08


def test_hill_min_k_enforcement():
    # Construct very small sample forcing k < 30 causing exception
    rng = np.random.default_rng(10)
    data = rng.pareto(a=3.0, size=40) + 1
    with pytest.raises(InsufficientTailSamples):
        hill_tail_index(data, k=10, min_k=5)
