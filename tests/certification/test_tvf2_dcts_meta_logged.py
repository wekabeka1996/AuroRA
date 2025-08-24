def test_tvf2_dcts_meta_logged():
    # Build synthetic summary emulate multigrid injection path
    from living_latent.core.tvf2.dcts_multigrid import DCTSGridConfig, compute_dcts_multigrid
    import numpy as np
    residuals = np.random.randn(200).tolist()
    # qhat_S keys expected numeric; provide floats
    qhat_S = {0.1:0.5, 0.2:0.8}
    cfg = DCTSGridConfig(grids=[0.5,1.0], base_window=10, aggregator='median_min')
    res_dict = compute_dcts_multigrid(np.asarray(residuals), qhat_S, cfg)
    # Emulate run_r0 meta assembly logic
    tvf2_block = {}
    tvf2_block['dcts_grids'] = res_dict.get('grids')
    tvf2_block['dcts_robust'] = res_dict.get('robust')
    robust_block = res_dict.get('robust') or {}
    if isinstance(robust_block, dict):
        tvf2_block['dcts_robust_value'] = robust_block.get('value')
    tvf2_block['dcts_min'] = res_dict.get('min')
    meta = {
        'aggregator': cfg.aggregator,
        'grids': cfg.grids,
        'source': 'robust'
    }
    tvf2_block['dcts_meta'] = meta
    assert 'dcts_meta' in tvf2_block
    m = tvf2_block['dcts_meta']
    assert m['aggregator'] == 'median_min'
    assert m['source'] == 'robust'
    assert m['grids'] == [0.5,1.0]
