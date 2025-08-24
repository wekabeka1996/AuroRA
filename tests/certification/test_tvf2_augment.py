import numpy as np
from living_latent.core.replay.summarize import augment_with_tvf2
from living_latent.core.certification.tvf2 import quantile_grid


def _fake_tail_snapshot(seed=0):
    rng = np.random.default_rng(seed)
    return {
        'xi': float(rng.normal(0.2, 0.01)),
        'theta_e': float(rng.normal(1.0, 0.05)),
        'lambda_U': float(rng.normal(0.05, 0.005)),
    }


def test_augment_with_tvf2_produces_fields():
    rng = np.random.default_rng(123)
    # Source summary with residuals and tail snapshot
    res_S = rng.normal(0, 1, 5000)
    source_summary = {
        'residuals': res_S[:1000].tolist(),  # as stored by run script
        'icp_qhat_grid': quantile_grid(res_S, alphas=(0.05, 0.1, 0.2, 0.3)),
        'tail_snapshot': _fake_tail_snapshot(1),
    }
    # Target summary
    res_T = rng.normal(0, 1.2, 4000)  # slight scale shift
    target_summary = {
        'residuals': res_T[:1000].tolist(),
        'tail_snapshot': _fake_tail_snapshot(2),
        'tvf_ctr': {'ctr': 0.95},  # emulate earlier CTR computation
    }
    augment_with_tvf2(target_summary, source_summary)
    assert 'tvf2' in target_summary, 'tvf2 key missing after augmentation'
    tvf2 = target_summary['tvf2']
    assert 'dcts' in tvf2, 'dcts not computed'
    assert tvf2['dcts'] is None or (0.0 <= tvf2['dcts'] <= 1.0)
    assert 'delta' in tvf2, 'delta invariants missing'
    # delta should have expected keys when both tail snapshots exist
    if tvf2['delta'] is not None:
        for k in ('d_xi', 'd_theta_e', 'd_lambda_U'):
            assert k in tvf2['delta']
    # ctr propagated
    assert 'ctr' in tvf2
