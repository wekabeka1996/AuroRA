import numpy as np
from certification.tvf import compute_ctr


def test_ctr_matched_distribution():
    rng = np.random.default_rng(42)
    # Source and target residuals from same normal distribution
    src = rng.normal(0, 1.0, size=2000)
    tgt = rng.normal(0, 1.0, size=2000)
    res = compute_ctr(src, tgt, alpha=0.1)
    # Expect coverage similarity -> ctr close to 1
    assert res.ctr > 0.95, f"CTR too low for matched distributions: {res.ctr}"
    assert abs(res.source_coverage - 0.9) < 0.03
    assert abs(res.target_coverage - 0.9) < 0.03


def test_ctr_higher_variance_target():
    rng = np.random.default_rng(43)
    src = rng.normal(0, 1.0, size=2000)
    tgt = rng.normal(0, 1.6, size=2000)  # heavier variance -> lower target coverage
    res = compute_ctr(src, tgt, alpha=0.1)
    # target coverage should drop below source coverage (compression)
    assert res.target_coverage < res.source_coverage
    # CTR should be meaningfully below 1
    assert res.ctr < 0.92, f"CTR unexpectedly high: {res.ctr}"
    assert res.source_coverage > 0.85  # sanity
    assert res.target_coverage < 0.83  # expected shrink due to variance expansion
