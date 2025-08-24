import numpy as np
from living_latent.core.risk.dro_es import get_scenarios

def test_tail_fraction_beyond_var95():
    rng = np.random.default_rng(0)
    hist = rng.normal(0, 0.01, size=5000)
    teacher_ext = rng.normal(0.05, 0.02, size=1000)
    n = 1000
    scen = get_scenarios(n, "volatility", {
        "history": hist,
        "teacher_extremes": teacher_ext,
        "xi_hat": 0.2,
        "scale_tail": 0.03,
    }, p_ext=0.10, seed=7)
    q95 = np.quantile(hist, 0.95)
    frac = (scen > q95).mean()
    assert frac >= 0.10 - 1e-6
