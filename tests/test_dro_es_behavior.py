import numpy as np
import pytest

from living_latent.core.dro_es import dro_es_objective

SEED = 1337
rng = np.random.default_rng(SEED)

def test_dro_es_monotonic_in_eps():
    losses = rng.normal(loc=0.0, scale=1.0, size=5000)
    idx = rng.integers(0, 5000, size=50)
    losses[idx] += 5.0
    eps_grid = [0.0, 0.01, 0.02, 0.05]
    es_values = [dro_es_objective(losses, es_alpha=0.975, eps=eps) for eps in eps_grid]
    assert all(es_values[i] <= es_values[i+1] + 1e-8 for i in range(len(es_values)-1))
