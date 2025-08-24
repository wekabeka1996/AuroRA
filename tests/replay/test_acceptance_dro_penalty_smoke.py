from living_latent.core.risk.dro_es import DROConfig, dro_es_optimize
import numpy as np

def test_acceptance_dro_penalty_smoke():
    rng = np.random.default_rng(0)
    scen = rng.normal(0, 1, size=256)
    cfg = DROConfig(alpha=0.1, eps_mode='fixed', eps=0.02)
    tail_snapshot = {'es_alpha': float(np.mean(np.sort(-scen)[-int(0.1*scen.size):]))}
    res = dro_es_optimize(scen, cfg, tail_snapshot=tail_snapshot)
    assert 'objective' in res and res['objective'] is not None
    assert res['objective'] >= 0.0
