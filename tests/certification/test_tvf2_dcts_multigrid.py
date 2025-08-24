import numpy as np
import json
from pathlib import Path

from living_latent.core.tvf2.dcts_multigrid import DCTSGridConfig, compute_dcts_multigrid
from living_latent.core.certification.tvf2 import compute_dcts, quantile_grid


def _make_series(seed: int, mode: str, n: int = 500):
    rng = np.random.default_rng(seed)
    if mode == 'trend':
        x = rng.normal(0,1,n) + np.linspace(0,2,n)
    elif mode == 'choppy':
        x = rng.normal(0,1.5,n) * (rng.random(n) > 0.5).astype(float)
    else:
        x = rng.standard_t(df=5, size=n)
    return x


def test_tvf2_dcts_multigrid_differs_from_single():
    src = _make_series(42,'trend',800)
    tgt = _make_series(43,'choppy',800)
    qhat_S = quantile_grid(src, alphas=[0.1,0.2,0.3,0.4])
    single = compute_dcts(tgt, qhat_S)
    cfg = DCTSGridConfig(grids=[0.5,1.0,2.0], base_window=20, aggregator='median_min')
    mg = compute_dcts_multigrid(tgt, qhat_S, cfg)
    grids_map = mg.get('grids') if isinstance(mg, dict) else None
    assert isinstance(grids_map, dict)
    values = list(grids_map.values())
    assert len(values) >= 2
    # ensure at least one grid value differs from single by >= 1e-6
    assert any(abs(v - single) >= 1e-6 for v in values), 'All multigrid values identical to single (unexpected)'


def test_variance_reduction_vs_single_grid():
    qsrc = _make_series(10,'trend',800)
    qhat_S = quantile_grid(qsrc, alphas=[0.1,0.2,0.3,0.4])
    cfg = DCTSGridConfig(grids=[0.5,1.0,2.0], base_window=25, aggregator='median_min')
    singles = []
    robusts = []
    rng = np.random.default_rng(123)
    for i in range(200):
        tgt = _make_series(1000+i, 'choppy', 600)
        singles.append(compute_dcts(tgt, qhat_S))
        mg_res = compute_dcts_multigrid(tgt, qhat_S, cfg)
        robust_block = mg_res.get('robust') if isinstance(mg_res, dict) else None
        assert isinstance(robust_block, dict)
        robusts.append(robust_block['value'])
    var_single = float(np.var(singles))
    var_robust = float(np.var(robusts))
    assert var_robust <= var_single * 0.85, f"Robust variance {var_robust} not reduced enough vs {var_single}"


def test_aggregator_modes():
    src = _make_series(55,'trend',600)
    tgt = _make_series(56,'choppy',600)
    qhat_S = quantile_grid(src, alphas=[0.1,0.2,0.3,0.4])
    cfg_med = DCTSGridConfig(grids=[0.7,1.0,1.6], base_window=18, aggregator='median')
    cfg_medmin = DCTSGridConfig(grids=[0.7,1.0,1.6], base_window=18, aggregator='median_min')
    r1_block = compute_dcts_multigrid(tgt, qhat_S, cfg_med).get('robust')
    r2_block = compute_dcts_multigrid(tgt, qhat_S, cfg_medmin).get('robust')
    assert isinstance(r1_block, dict) and isinstance(r2_block, dict)
    r1 = r1_block['value']
    r2 = r2_block['value']
    # They can coincide, but we allow equality; if always equal across seeds, aggregator adds no value.
    # Just ensure they are finite.
    assert np.isfinite(r1) and np.isfinite(r2)

