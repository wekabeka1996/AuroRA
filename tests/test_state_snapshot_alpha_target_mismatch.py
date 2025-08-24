from living_latent.core.icp_dynamic import AdaptiveICP
from living_latent.state.snapshot import load_icp_state

def test_alpha_target_mismatch_warning(capfd):
    icp = AdaptiveICP(alpha_target=0.10, eta=0.01, window=64, quantile_mode='p2')
    payload = {
        'alpha': 0.12,
        'alpha_target': 0.07,  # mismatch
        'coverage_ema': 0.91,
        'deque_scores': {'data': [1.0, 0.5, 0.8], 'maxlen': 64}
    }
    load_icp_state(icp, payload)
    out, err = capfd.readouterr()
    assert 'alpha_target mismatch' in out
    assert abs(icp.alpha_target - 0.10) < 1e-12  # unchanged
