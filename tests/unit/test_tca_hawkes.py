
from core.tca.hawkes import HawkesParams, simulate, fit_em, loglik


def test_em_increases_loglik_on_simulated_hawkes():
    # True process
    true_params = HawkesParams(mu=0.5, eta=0.3, beta=1.2)
    T = 100.0
    times = simulate(true_params, T=T, seed=0)

    # Initialization far from truth
    init = HawkesParams(mu=0.1, eta=0.1, beta=0.5)
    ll_init = loglik(times, init, T=T)

    est = fit_em(times, T=T, max_iter=100, tol=1e-6, init=init)
    ll_est = loglik(times, est, T=T)

    # EM should not reduce log-likelihood
    assert ll_est >= ll_init - 1e-9

    # Valid parameter ranges
    assert est.mu > 0.0
    assert 0.0 < est.eta < 1.0
    assert est.beta > 0.0


def test_simulate_sorted_and_within_bounds():
    T = 10.0
    times = simulate(HawkesParams(mu=0.2, eta=0.2, beta=1.0), T=T, seed=1)
    assert times == sorted(times)
    assert all(0.0 <= t <= T for t in times)