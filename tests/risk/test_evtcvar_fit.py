import math
import random
from core.risk.evtcvar import EVTCVaR


def test_evt_fit_and_cvar_monotonic():
    random.seed(0)
    # Synthetic heavy tail (Pareto-like)
    losses=[]
    for _ in range(5000):
        u=random.random()
        x=(1/(1-u))**1.5 - 1  # heavy tail >0
        losses.append(x)
    evt=EVTCVaR(min_exceedances=100)
    fit=evt.fit(losses, u_quantile=0.95)
    assert fit['n'] == len(losses)
    assert fit['n_exc'] >= 100
    assert fit['u']>=0
    # cvar should be finite and increase with alpha
    c1=evt.cvar(0.90)
    c2=evt.cvar(0.95)
    c3=evt.cvar(0.99)
    assert all(math.isfinite(c) for c in (c1,c2,c3))
    assert c1 <= c2 <= c3


def test_evt_fallback_when_few_exceedances():
    losses=[0.1,0.2,0.3,0.4,0.5, 10.0]  # small sample
    evt=EVTCVaR(min_exceedances=50)
    fit=evt.fit(losses, u_quantile=0.95)
    # fallback path keeps xi=0
    assert fit['n_exc'] < 50
    assert fit['xi'] == 0.0
