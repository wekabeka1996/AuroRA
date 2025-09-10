"""
Aurora+ScalpBot — repo/core/features/scaling.py
-----------------------------------------------
Online feature scalers for streaming pipelines.

Paste into: repo/core/features/scaling.py
Run self-tests: `python repo/core/features/scaling.py`

Implements (per project structure):
- Welford z-score (online mean/variance) with clipping & inverse
- Robust scaler: online P²-estimator for median and MAD → robust z-score
- Hysteresis Min–Max: adaptive bounds with fast expand, slow shrink, + inverse
- DictFeatureScaler: per-feature stateful scalers (whitelist-friendly)

I/O Contract:
- Input: streaming float values, event-time timestamps (no look-ahead bias)
- Output: scaled values in [-clip_hi, +clip_hi] range, dimensionless z-scores
- Invariants: monotonicity inverse(transform(x)) ≈ x within tolerance
- Units: all inputs/outputs dimensionless (normalized features)
- Event-time: processes data in chronological order, no future information

Example integration with DictFeatureScaler whitelist from config:
    ```python
    from core.config import get_feature_whitelist
    dfs = DictFeatureScaler(mode="robust", clip=(-6, 6))
    whitelist = get_feature_whitelist()  # e.g., ["obi", "tfi", "microprice"]
    for feat_name, value in features.items():
        if feat_name in whitelist:
            scaled = dfs.update(feat_name, value)
            # use scaled for model input
    ```

No external dependencies; NumPy optional. Fully standalone.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import math
import random

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# =============================
# Utilities
# =============================

def _clip(x: float, lo: float | None, hi: float | None) -> float:
    if lo is not None and x < lo:
        return lo
    if hi is not None and x > hi:
        return hi
    return x


# =============================
# Welford online stats
# =============================

@dataclass
class Welford:
    n: int = 0
    mean: float = 0.0
    M2: float = 0.0

    def update(self, x: float) -> None:
        self.n += 1
        dx = x - self.mean
        self.mean += dx / self.n
        self.M2 += dx * (x - self.mean)

    @property
    def var(self) -> float:
        return 0.0 if self.n < 2 else self.M2 / (self.n - 1)

    @property
    def std(self) -> float:
        v = self.var
        return math.sqrt(v) if v > 0 else 0.0


# =============================
# P² quantile estimator (Jain & Chlamtac, 1985)
# =============================

@dataclass
class P2Quantile:
    q: float  # desired quantile in (0,1)
    _init: list[float] = field(default_factory=list)
    # marker positions (n), desired positions (np), heights (q)
    n: list[float] = field(default_factory=lambda: [0.0]*5)
    np_des: list[float] = field(default_factory=lambda: [0.0]*5)
    dn: list[float] = field(default_factory=lambda: [0.0]*5)
    qh: list[float] = field(default_factory=lambda: [0.0]*5)

    def update(self, x: float) -> None:
        x = float(x)
        if not (0.0 < self.q < 1.0):
            raise ValueError("quantile q must be in (0,1)")
        if len(self._init) < 5:
            self._init.append(x)
            if len(self._init) == 5:
                self._init.sort()
                self.qh = [self._init[i] for i in range(5)]
                self.n = [1, 2, 3, 4, 5]
                self.np_des = [1, 1 + 2 * self.q, 1 + 4 * self.q, 3 + 2 * self.q, 5]
                self.dn = [0, self.q/2, self.q, (1 + self.q)/2, 1]
            return
        # locate cell k
        k = 0
        if x < self.qh[0]:
            self.qh[0] = x
            k = 0
        elif x >= self.qh[4]:
            self.qh[4] = x
            k = 3
        else:
            for i in range(4):
                if self.qh[i] <= x < self.qh[i + 1]:
                    k = i
                    break
        # increment positions
        for i in range(k + 1, 5):
            self.n[i] += 1
        for i in range(5):
            self.np_des[i] += self.dn[i]
        # adjust heights for i=1..3
        for i in range(1, 4):
            d = self.np_des[i] - self.n[i]
            if (d >= 1 and self.n[i + 1] - self.n[i] > 1) or (d <= -1 and self.n[i - 1] - self.n[i] < -1):
                d_sign = 1 if d >= 0 else -1
                # parabolic prediction
                q_new = self.qh[i] + d_sign * (
                    (self.n[i] - self.n[i - 1] + d_sign) * (self.qh[i + 1] - self.qh[i]) / max(1e-12, self.n[i + 1] - self.n[i]) +
                    (self.n[i + 1] - self.n[i] - d_sign) * (self.qh[i] - self.qh[i - 1]) / max(1e-12, self.n[i] - self.n[i - 1])
                ) / max(1e-12, self.n[i + 1] - self.n[i - 1])
                # if parabolic prediction is not monotone, use linear
                if not (self.qh[i - 1] <= q_new <= self.qh[i + 1]):
                    if d_sign > 0:
                        q_new = self.qh[i] + (self.qh[i + 1] - self.qh[i]) / max(1e-12, self.n[i + 1] - self.n[i])
                    else:
                        q_new = self.qh[i] - (self.qh[i - 1] - self.qh[i]) / max(1e-12, self.n[i - 1] - self.n[i])
                self.qh[i] = q_new
                self.n[i] += d_sign

    def value(self) -> float:
        if len(self._init) < 5:
            if not self._init:
                return 0.0
            s = sorted(self._init)
            k = int(round((len(s)-1) * self.q))
            return s[k]
        return float(self.qh[2])


# =============================
# Robust median/MAD using P² (approx.)
# =============================

@dataclass
class RobustMedianMAD:
    q_med: P2Quantile = field(default_factory=lambda: P2Quantile(0.5))
    q_mad: P2Quantile = field(default_factory=lambda: P2Quantile(0.5))
    c: float = 0.6744897501960817  # Φ^{-1}(0.75), to make MAD ~ σ for Gaussian

    def update(self, x: float) -> None:
        m = self.q_med.value()
        self.q_med.update(x)
        # use previous median to update MAD estimator with |x - m|
        self.q_mad.update(abs(x - m))

    @property
    def median(self) -> float:
        return self.q_med.value()

    @property
    def mad(self) -> float:
        return self.q_mad.value() / max(1e-12, self.c)


# =============================
# Scalers
# =============================

@dataclass
class ZScoreScaler:
    clip_lo: float | None = -5.0
    clip_hi: float | None = 5.0
    stats: Welford = field(default_factory=Welford)

    def update(self, x: float) -> float:
        self.stats.update(float(x))
        return self.transform(x)

    def transform(self, x: float) -> float:
        mu = self.stats.mean
        sd = self.stats.std
        z = 0.0 if sd <= 0 else (float(x) - mu) / sd
        return _clip(z, self.clip_lo, self.clip_hi)

    def inverse(self, z: float) -> float:
        mu = self.stats.mean
        sd = self.stats.std
        return mu + float(z) * (sd if sd > 0 else 1.0)


@dataclass
class RobustScaler:
    clip_lo: float | None = -5.0
    clip_hi: float | None = 5.0
    r: RobustMedianMAD = field(default_factory=RobustMedianMAD)

    def update(self, x: float) -> float:
        self.r.update(float(x))
        return self.transform(x)

    def transform(self, x: float) -> float:
        med = self.r.median
        mad = self.r.mad
        z = 0.0 if mad <= 0 else (float(x) - med) / mad
        # 0.6745⋅(x−median)/MAD often used; here MAD already scaled to ~σ
        return _clip(z, self.clip_lo, self.clip_hi)

    def inverse(self, z: float) -> float:
        med = self.r.median
        mad = self.r.mad
        return med + float(z) * (mad if mad > 0 else 1.0)


@dataclass
class HysteresisMinMax:
    # expansion reacts fast (small alpha_expand), shrink reacts slow (alpha_shrink close to 1)
    alpha_expand: float = 0.1
    alpha_shrink: float = 0.995
    lo: float | None = None
    hi: float | None = None

    def update(self, x: float) -> float:
        x = float(x)
        if self.lo is None or self.hi is None:
            self.lo = x
            self.hi = x
            return 0.5  # neutral
        if x > self.hi:
            # expand up quickly
            self.hi = self.alpha_expand * self.hi + (1.0 - self.alpha_expand) * x
        elif x < self.lo:
            # expand down quickly
            self.lo = self.alpha_expand * self.lo + (1.0 - self.alpha_expand) * x
        else:
            # shrink slowly toward x to prevent overfitting to transient spikes
            self.hi = self.alpha_shrink * self.hi + (1.0 - self.alpha_shrink) * x
            self.lo = self.alpha_shrink * self.lo + (1.0 - self.alpha_shrink) * x
        return self.transform(x)

    def transform(self, x: float) -> float:
        if self.lo is None or self.hi is None or self.hi <= self.lo:
            return 0.5
        return _clip((float(x) - self.lo) / (self.hi - self.lo), 0.0, 1.0)

    def inverse(self, y: float) -> float:
        if self.lo is None or self.hi is None or self.hi <= self.lo:
            return 0.0
        y = _clip(float(y), 0.0, 1.0)
        return self.lo + y * (self.hi - self.lo)


# =============================
# DictFeatureScaler — stateful per-feature transforms
# =============================

class DictFeatureScaler:
    """Apply a chosen scaler per feature key. Useful for pipelines.

    Usage:
        dfs = DictFeatureScaler(mode="robust", clip=(-6, 6))
        y = dfs.update_batch({"obi": 0.2, "tfi": 15.0})
    """
    def __init__(self, *, mode: str = "robust", clip: tuple[float | None, float | None] = (None, None)) -> None:
        self.mode = mode
        self.clip = clip
        self._scalers: dict[str, object] = {}

    def _make(self) -> object:
        lo, hi = self.clip
        if self.mode == "zscore":
            return ZScoreScaler(clip_lo=lo, clip_hi=hi)
        if self.mode == "robust":
            return RobustScaler(clip_lo=lo, clip_hi=hi)
        if self.mode == "minmax":
            return HysteresisMinMax()
        raise ValueError("Unknown mode: %s" % self.mode)

    def update(self, key: str, x: float) -> float:
        sc = self._scalers.get(key)
        if sc is None:
            sc = self._make()
            self._scalers[key] = sc
        return sc.update(float(x))  # type: ignore

    def transform(self, key: str, x: float) -> float:
        sc = self._scalers.get(key)
        if sc is None:
            sc = self._make()
            self._scalers[key] = sc
        return sc.transform(float(x))  # type: ignore

    def update_batch(self, feats: Mapping[str, float]) -> dict[str, float]:
        return {k: self.update(k, v) for k, v in feats.items()}


# =============================
# Self-tests
# =============================

def _test_welford_basic() -> None:
    ws = Welford()
    xs = [1.0, 2.0, 3.0, 4.0]
    for x in xs:
        ws.update(x)
    assert abs(ws.mean - 2.5) < 1e-12
    assert abs(ws.var - 1.6666666666666667) < 1e-12


def _test_zscore_inverse() -> None:
    zs = ZScoreScaler()
    for x in [10, 12, 11, 9, 13, 12, 11]:
        zs.update(x)
    z = zs.transform(12)
    x_back = zs.inverse(z)
    assert abs(x_back - 12) < 1e-6


def _test_robust_outlier_resistance() -> None:
    rs = RobustScaler()
    # mostly N(0,1), inject a large outlier
    rnd = random.Random(7)
    for _ in range(500):
        rs.update(rnd.gauss(0.0, 1.0))
    base = rs.transform(5.0)
    # inject extreme outlier — should not blow up scaling state
    for _ in range(5):
        rs.update(50.0)
    after = rs.transform(5.0)
    assert abs(after - base) < 0.5  # robust scaler should be stable


def _test_monotonicity_inverse() -> None:
    """Test inverse(transform(x)) ≈ x within tolerance."""
    for scaler_cls in [ZScoreScaler, RobustScaler]:
        scaler = scaler_cls(clip_lo=-10, clip_hi=10)
        test_values = [-5.0, -1.0, 0.0, 1.0, 5.0, 10.0]
        for x in test_values:
            scaler.update(x)
            z = scaler.transform(x)
            x_back = scaler.inverse(z)
            assert abs(x_back - x) < 1e-6, f"Failed for {scaler_cls.__name__} at x={x}"


def _test_robust_seed_stability() -> None:
    """Test that RobustScaler produces stable results with same seed."""
    seed = 42
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    # First run
    rs1 = RobustScaler()
    rnd1 = random.Random(seed)
    for _ in range(100):
        rs1.update(rnd1.gauss(0.0, 1.0))
    result1 = rs1.transform(2.0)

    # Second run with same seed
    rs2 = RobustScaler()
    rnd2 = random.Random(seed)
    for _ in range(100):
        rs2.update(rnd2.gauss(0.0, 1.0))
    result2 = rs2.transform(2.0)

    assert abs(result1 - result2) < 1e-12, "RobustScaler should be deterministic with same seed"


def _test_minmax_bounds() -> None:
    mm = HysteresisMinMax(alpha_expand=0.05, alpha_shrink=0.99)
    vals = [0, 1, 2, 3, 4, 5]
    outs = [mm.update(v) for v in vals]
    assert all(0.0 <= y <= 1.0 for y in outs)
    # inverse within current bounds
    z = mm.transform(3.0)
    x = mm.inverse(z)
    assert abs(x - 3.0) < 1e-6


def _test_dict_feature_scaler() -> None:
    dfs = DictFeatureScaler(mode="robust", clip=(-6, 6))
    a = dfs.update("obi", 0.1)
    b = dfs.update("tfi", 20.0)
    c = dfs.update("obi", 0.2)
    assert isinstance(a, float) and isinstance(b, float) and isinstance(c, float)


if __name__ == "__main__":
    _test_welford_basic()
    _test_zscore_inverse()
    _test_robust_outlier_resistance()
    _test_minmax_bounds()
    _test_dict_feature_scaler()
    _test_monotonicity_inverse()
    _test_robust_seed_stability()
    print("OK - repo/core/features/scaling.py self-tests passed")
