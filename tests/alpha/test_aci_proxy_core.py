import numpy as np
from pathlib import Path

from living_latent.core.alpha.aci_proxy import realized_vol, compute_aci_proxy, rolling_corr

def test_realized_vol_basic():
    x = np.linspace(0, 10, 200) + np.random.randn(200) * 0.01
    rv = realized_vol(x, window=20)
    assert rv.shape == x.shape
    # first window-1 are nan
    assert np.isnan(rv[:19]).all()
    assert np.isfinite(rv[25:]).all()


def test_compute_aci_proxy_scale_and_smooth():
    rng = np.random.default_rng(42)
    x = rng.normal(0, 1, size=500)
    proxy = compute_aci_proxy(x, window=30, smooth=10)
    assert proxy.shape == x.shape
    # NaNs only in warmup region
    warm = 29  # window-1
    assert np.isnan(proxy[:warm]).all()
    assert np.isfinite(proxy[warm+10:]).all()


def test_rolling_corr_high_on_scaled_series():
    rng = np.random.default_rng(123)
    base = rng.normal(0, 1, size=400)
    noisy_scale = 2.0
    ref = base * noisy_scale + rng.normal(0, 0.05, size=400)
    c = rolling_corr(base, ref, window=50)
    # After warmup correlation should be high (>0.9 median ignoring NaNs)
    tail = c[~np.isnan(c)][60:]
    assert tail.size > 50
    median_corr = float(np.median(tail))
    assert median_corr > 0.9, median_corr
