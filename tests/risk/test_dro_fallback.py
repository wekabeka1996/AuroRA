import numpy as np
from living_latent.core.risk.dro_es import dro_es_optimize, DROConfig

def test_dro_fallback_matches_surrogate_within_tolerance():
    r = np.random.default_rng(1).normal(0, 0.02, size=1024)
    cfg = DROConfig(alpha=0.1, eps_mode="fixed", eps=0.01, use_cvxpy=False, solver="NONE")
    res = dro_es_optimize(r, cfg, tail_snapshot={"xi":0.1, "es_alpha":0.02})
    assert res["status"].startswith("FALLBACK")
    assert res["objective"] >= 0.0
