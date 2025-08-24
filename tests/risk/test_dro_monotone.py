import numpy as np
from living_latent.core.risk.dro_es import dro_es_optimize, DROConfig

def test_dro_objective_monotone_in_eps():
    r = np.random.default_rng(0).normal(0, 0.01, size=512)
    cfg_lo = DROConfig(alpha=0.1, eps_mode="fixed", eps=0.0, use_cvxpy=False)
    cfg_hi = DROConfig(alpha=0.1, eps_mode="fixed", eps=0.05, use_cvxpy=False)
    o_lo = dro_es_optimize(r, cfg_lo, tail_snapshot={"xi":0.2}).get("objective")
    o_hi = dro_es_optimize(r, cfg_hi, tail_snapshot={"xi":0.2}).get("objective")
    assert o_hi >= o_lo
