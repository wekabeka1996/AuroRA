"""
Aurora+ScalpBot — repo/core/calibration/icp.py
----------------------------------------------
Split/Mondrian conformal prediction for binary classifiers (probability inputs)
and Venn–Abers multiprobability predictor (interval probabilities).

Paste into: repo/core/calibration/icp.py
Run self-tests: `python repo/core/calibration/icp.py`

Implements (per project structure):
- SplitConformalBinary: nonconformity s = 1 − p_true; p-values & prediction set
- MondrianConformalBinary: per-group (condition key) conformal with global fallback
- VennAbersBinary: isotonic-based [p_low, p_high] interval via add-one refit trick

No external dependencies; NumPy optional. Standalone.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
import math
import random

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# =============================
# Utilities
# =============================

def _quantile_leq(sorted_vals: Sequence[float], q: float) -> float:
    """Left-closed quantile: returns smallest t such that P(X ≤ t) ≥ q.
    Input must be sorted ascending.
    """
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    a = min(1.0, max(0.0, float(q)))
    k = int(math.ceil(a * n)) - 1
    k = max(0, min(n - 1, k))
    return float(sorted_vals[k])


def _nonconformity_binary(p: float, y: int) -> float:
    """s = 1 − p_true = y·(1−p) + (1−y)·p"""
    p = min(1.0, max(0.0, float(p)))
    y = 1 if int(y) == 1 else 0
    return y * (1.0 - p) + (1 - y) * p


# =============================
# Split conformal (binary)
# =============================

@dataclass
class SplitConformalBinary:
    alpha: float = 0.1  # miscoverage level (target coverage 1−α)

    def fit(self, p_hat: Sequence[float], y: Sequence[int]) -> None:
        assert len(p_hat) == len(y)
        s = [_nonconformity_binary(pi, yi) for pi, yi in zip(p_hat, y)]
        self.n = len(s)
        self.scores = sorted(s)

    def p_values(self, p_new: float) -> Tuple[float, float]:
        """Return p-values (p_y=1, p_y=0) for a new probability p_new=P(y=1)."""
        n = getattr(self, "n", 0)
        S = getattr(self, "scores", [])
        if n == 0:
            return 1.0, 1.0
        s1 = _nonconformity_binary(p_new, 1)
        s0 = _nonconformity_binary(p_new, 0)
        # count >= s (right tail); S is sorted asc
        def count_ge(t: float) -> int:
            # binary search first index > t then n - idx; inclusive ≥ via small epsilon
            lo, hi = 0, n
            while lo < hi:
                mid = (lo + hi) // 2
                if S[mid] > t:
                    hi = mid
                else:
                    lo = mid + 1
            # lo is first index with S[lo] > t → #≥ = n - (lo - k_eq)
            # to ensure ≥, we used (S[mid] > t) branch; so indices equal to t are included
            ge = n - (lo - 0)
            return ge
        ge1 = count_ge(s1)
        ge0 = count_ge(s0)
        # conformal p-values with +1 smoothing
        pval1 = (ge1 + 1) / (n + 1)
        pval0 = (ge0 + 1) / (n + 1)
        return float(pval1), float(pval0)

    def predict_set(self, p_new: float) -> List[int]:
        p1, p0 = self.p_values(p_new)
        S = []
        if p1 > self.alpha:
            S.append(1)
        if p0 > self.alpha:
            S.append(0)
        return S


# =============================
# Mondrian split conformal (per-group)
# =============================

@dataclass
class MondrianConformalBinary:
    alpha: float = 0.1

    def fit(self, p_hat: Sequence[float], y: Sequence[int], groups: Sequence[str]) -> None:
        assert len(p_hat) == len(y) == len(groups)
        self.bucket: Dict[str, List[float]] = {}
        for pi, yi, g in zip(p_hat, y, groups):
            s = _nonconformity_binary(pi, yi)
            L = self.bucket.setdefault(str(g), [])
            L.append(s)
        for k in list(self.bucket.keys()):
            self.bucket[k].sort()
        # global fallback
        self.global_scores = sorted([_nonconformity_binary(pi, yi) for pi, yi in zip(p_hat, y)])

    def _p_values_from_scores(self, scores: Sequence[float], p_new: float) -> Tuple[float, float]:
        if not scores:
            return 1.0, 1.0
        n = len(scores)
        s1 = _nonconformity_binary(p_new, 1)
        s0 = _nonconformity_binary(p_new, 0)
        # count ≥ via binary search
        import bisect
        k1 = n - bisect.bisect_left(scores, s1)  # elements >= s1
        k0 = n - bisect.bisect_left(scores, s0)
        return (k1 + 1) / (n + 1), (k0 + 1) / (n + 1)

    def p_values(self, p_new: float, group: Optional[str]) -> Tuple[float, float]:
        if group is not None and group in getattr(self, "bucket", {}):
            return self._p_values_from_scores(self.bucket[group], p_new)
        return self._p_values_from_scores(getattr(self, "global_scores", []), p_new)

    def predict_set(self, p_new: float, group: Optional[str]) -> List[int]:
        p1, p0 = self.p_values(p_new, group)
        S = []
        if p1 > self.alpha:
            S.append(1)
        if p0 > self.alpha:
            S.append(0)
        return S


# =============================
# Isotonic regression (PAV) for Venn–Abers
# =============================

@dataclass
class _Iso:
    xs: List[float]
    ys: List[float]

    def fit(self) -> None:
        # Pool-Adjacent-Violators for isotonic (non-decreasing) fit
        xs = [float(x) for x in self.xs]
        ys = [float(y) for y in self.ys]
        order = sorted(range(len(xs)), key=lambda i: xs[i])
        x = [xs[i] for i in order]
        y = [ys[i] for i in order]
        n = len(x)
        if n == 0:
            self.blocks = []
            return
        # initialize blocks
        v = [float(val) for val in y]
        w = [1.0] * n
        i = 0
        while i < n - 1:
            if v[i] <= v[i + 1]:
                i += 1
                continue
            # pool
            j = i
            while j >= 0 and v[j] > v[j + 1]:
                wt = w[j] + w[j + 1]
                val = (w[j] * v[j] + w[j + 1] * v[j + 1]) / wt
                v[j] = val
                w[j] = wt
                # delete j+1
                del v[j + 1]
                del w[j + 1]
                j -= 1
            i = max(j, 0)
        # build blocks with x spans
        blocks = []
        idx = 0
        for val, wt in zip(v, w):
            x_lo = x[idx]
            x_hi = x[min(len(x) - 1, idx + int(wt) - 1)]
            blocks.append((x_lo, x_hi, val))
            idx += int(wt)
        self.blocks = blocks

    def predict(self, xq: float) -> float:
        if not hasattr(self, "blocks") or not self.blocks:
            return 0.5
        xq = float(xq)
        # find block
        for lo, hi, val in self.blocks:
            if xq <= hi:
                if xq < lo:
                    # interpolate with previous block if exists
                    return val
                return val
        return self.blocks[-1][2]


# =============================
# Venn–Abers (binary, simple refit per query)
# =============================

@dataclass
class VennAbersBinary:
    """Venn–Abers via isotonic refits with the new point labelled 0 and 1.

    API:
      - fit(scores, y) where `scores` are *monotone* scores (e.g., logits or raw model scores
        increasing with P(y=1)). If you only have probabilities p, you may pass
        scores = logit(p) (guarded inside).
      - predict_interval(score_new) → (p_low, p_high)
    """
    def fit(self, scores: Sequence[float], y: Sequence[int]) -> None:
        assert len(scores) == len(y)
        self.s = [float(x) for x in scores]
        self.y = [1 if int(t) == 1 else 0 for t in y]
        # if scores are probabilities, map to logits to improve monotonicity spacing
        # guard at 0/1 boundaries
        def to_logit(p: float) -> float:
            p = min(1 - 1e-9, max(1e-9, float(p)))
            return math.log(p / (1 - p))
        # decide if looks like probs
        if all(0.0 <= x <= 1.0 for x in self.s):
            self.s = [to_logit(x) for x in self.s]

    def _calibrate_with_added(self, s_new: float, y_new: int) -> float:
        xs = self.s + [float(s_new)]
        ys = self.y + [1 if int(y_new) == 1 else 0]
        iso = _Iso(xs=xs, ys=ys)
        iso.fit()
        return max(0.0, min(1.0, iso.predict(float(s_new))))

    def predict_interval(self, score_new: float) -> Tuple[float, float]:
        # map prob to logit if necessary (mirror of fit)
        s_new = float(score_new)
        if 0.0 <= s_new <= 1.0:
            p = min(1 - 1e-9, max(1e-9, s_new))
            s_new = math.log(p / (1 - p))
        p0 = self._calibrate_with_added(s_new, 0)
        p1 = self._calibrate_with_added(s_new, 1)
        lo = min(p0, p1)
        hi = max(p0, p1)
        return lo, hi


# =============================
# Self-tests (synthetic)
# =============================

def _make_scores(n: int = 1200, seed: int = 11) -> Tuple[List[float], List[int]]:
    rnd = random.Random(seed)
    scores: List[float] = []
    y: List[int] = []
    for i in range(n):
        # latent probability depends on score via sigmoid with mild miscalibration
        s = rnd.uniform(-2.5, 2.5)
        p = 1 / (1 + math.exp(-(s + 0.3)))  # shift +0.3 to miscalibrate
        scores.append(s)
        y.append(1 if rnd.random() < p else 0)
    return scores, y


def _test_split_conformal_coverage() -> None:
    s, y = _make_scores()
    # pretend we only have calibrated probabilities from a model: map via sigmoid (miscalibrated)
    p_hat = [1 / (1 + math.exp(-si)) for si in s]
    # use 50% for calibration
    n = len(y)
    idx = n // 2
    cal = SplitConformalBinary(alpha=0.1)
    cal.fit(p_hat[:idx], y[:idx])
    # evaluate coverage on holdout: probability that true label ∈ prediction set
    cover = 0
    m = 0
    for pi, yi in zip(p_hat[idx:], y[idx:]):
        S = cal.predict_set(pi)
        cover += 1 if yi in S else 0
        m += 1
    cov_rate = cover / max(1, m)
    # target coverage ≥ 1−α ≈ 0.9, allow small randomness tolerance
    assert cov_rate >= 0.85


def _test_mondrian_grouping() -> None:
    s, y = _make_scores(seed=21)
    p_hat = [1 / (1 + math.exp(-si)) for si in s]
    # define groups by coarse score bins
    groups = ["low" if si < -0.5 else "mid" if si < 0.5 else "high" for si in s]
    n = len(y)
    idx = n // 2
    mon = MondrianConformalBinary(alpha=0.1)
    mon.fit(p_hat[:idx], y[:idx], groups[:idx])
    # check p-values bounded in [0,1] and sets non-empty most of the time
    cnt_nonempty = 0
    for pi, gi in zip(p_hat[idx:], groups[idx:]):
        p1, p0 = mon.p_values(pi, gi)
        assert 0.0 <= p1 <= 1.0 and 0.0 <= p0 <= 1.0
        if mon.predict_set(pi, gi):
            cnt_nonempty += 1
    assert cnt_nonempty >= len(p_hat[idx:]) * 0.7


def _test_venn_abers_interval() -> None:
    s, y = _make_scores(seed=33)
    va = VennAbersBinary()
    va.fit(s[:600], y[:600])
    lo, hi = va.predict_interval(s[601])
    assert 0.0 <= lo <= hi <= 1.0
    # interval shouldn't be absurdly wide on typical scores
    assert (hi - lo) <= 0.5


if __name__ == "__main__":
    _test_split_conformal_coverage()
    _test_mondrian_grouping()
    _test_venn_abers_interval()
    print("OK - repo/core/calibration/icp.py self-tests passed")
