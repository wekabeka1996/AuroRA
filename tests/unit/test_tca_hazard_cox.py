import math
import random

from core.tca.hazard_cox import CoxPH


def _gen_synthetic_cox(n=400, beta_true=1.0, base=0.01, cens=0.005, seed=0):
    random.seed(seed)
    data = []
    for _ in range(n):
        x = random.gauss(0.0, 1.0)
        rate = base * math.exp(beta_true * x)
        # Exponential event and censoring times
        t_event = random.expovariate(rate)
        t_cens = random.expovariate(cens)
        t = t_event if t_event <= t_cens else t_cens
        d = 1 if t_event <= t_cens else 0
        data.append({"t": t, "d": d, "z": {"x": x}})
    return data


def test_cox_recovers_positive_sign_and_hr_monotonic():
    data = _gen_synthetic_cox(n=500, beta_true=1.0, base=0.02, cens=0.01, seed=1)
    model = CoxPH(l2=1e-4, max_iter=200, tol=1e-6, step=0.5)
    res = model.fit(data)

    b = res.beta.get("x", 0.0)
    assert b > 0.0  # positive effect should be learned

    # hazard ratio must be monotone in x
    hr_low = model.hazard_ratio({"x": -1.0})
    hr_mid = model.hazard_ratio({"x": 0.0})
    hr_high = model.hazard_ratio({"x": 1.0})
    assert hr_low < hr_mid < hr_high


def test_cox_handles_ties_and_returns_valid_result():
    data = _gen_synthetic_cox(n=200, beta_true=0.7, base=0.02, cens=0.015, seed=2)
    # Create ties by rounding times
    for rec in data:
        rec["t"] = round(rec["t"], 2)
    model = CoxPH(l2=1e-4, max_iter=150, tol=1e-6, step=0.5)
    res = model.fit(data)
    assert isinstance(res.loglik, float)
    assert isinstance(res.iters, int) and 1 <= res.iters <= model.max_iter

    # Sanity: coefficients finite
    for v in res.beta.values():
        assert math.isfinite(v)