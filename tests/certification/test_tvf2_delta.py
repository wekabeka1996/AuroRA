from living_latent.core.certification.tvf2 import delta_invariants


def test_delta_invariants_basic():
    src = {'xi': 0.2, 'theta_e': 1.0, 'lambda_U': 0.05}
    tgt = {'xi': 0.25, 'theta_e': 0.8, 'lambda_U': 0.10}
    d = delta_invariants(src, tgt)
    assert abs(d['d_xi'] - 0.05) < 1e-9
    assert abs(d['d_theta_e'] + 0.2) < 1e-9
    assert abs(d['d_lambda_U'] - 0.05) < 1e-9


def test_delta_invariants_missing_keys():
    src = {'xi': 0.1}
    tgt = {'theta_e': 1.2}
    d = delta_invariants(src, tgt)
    assert d['d_xi'] is None or d['d_xi'] == 0.0  # one side missing -> None
    assert d['d_theta_e'] is None
    assert d['d_lambda_U'] is None
