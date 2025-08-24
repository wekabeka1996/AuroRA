import json
from living_latent.core.replay.summarize import augment_with_tvf2

def test_replay_summary_tvf2_smoke():
    # Minimal synthetic summary emulating run_r0 output before augmentation
    summary = {
        'residuals': [0.0, 0.1, -0.2, 0.3],
        'icp_qhat_grid': {0.05: 1.0, 0.1: 0.9},
        'tail_snapshot': {'xi': 0.2, 'theta_e': 1.0, 'lambda_U': 0.05},
        'tvf_ctr': {'ctr': 0.97},
    }
    augment_with_tvf2(summary, source_summary=summary)
    assert 'tvf2' in summary
    tvf2 = summary['tvf2']
    assert 'dcts' in tvf2
    # Accept possible None if compute failed, but typically should be float
    if tvf2['dcts'] is not None:
        assert 0.0 <= tvf2['dcts'] <= 1.0
    assert 'delta' in tvf2
