from __future__ import annotations

"""
Calibration — Platt / Isotonic + Prequential Metrics
====================================================

Provides probability calibration modules and online (prequential) metrics for
score quality monitoring.

Key Concepts
------------
Given an input signal converted to a *raw probability* p_raw \in (0,1), we
apply a calibration map C: (0,1) -> (0,1) to obtain calibrated p. Two methods:

- Platt scaling (logistic calibration): p = sigmoid(a * logit(p_raw) + b)
- Isotonic regression (nonparametric, monotone): p = f_iso(z), where z is either
  p_raw or a score mapped monotonically to [0,1].

We recommend calibrating over out-of-sample data (time-wise split) and
monitoring prequential metrics (ECE, Brier, LogLoss) in live/shadow.

API
---
    cal = ProbabilityCalibrator(method="isotonic")
    cal.fit(p_raw=[...], y=[0/1,...])
    p = cal.calibrate_prob(0.62)

    # Prequential metrics:
    m = PrequentialMetrics(bins=10)
    for p, y in stream:
        m.update(p, y)
    print(m.ece(), m.brier(), m.logloss())

Notes
-----
- No external dependencies (pure Python); numerically stable logistic/entropy.
- Isotonic uses PAVA; inference via right-constant step function (monotone, robust).
- Platt trained by Newton–Raphson with L2 ridge (small) for stability; fallbacks
  to constant calibrator if degenerate (e.g., all targets equal).
"""

from dataclasses import dataclass
from typing import Iterable, List, Sequence, Tuple, Optional

# -------------------- numeric helpers --------------------

def _clip(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def _sigmoid(z: float) -> float:
    if z >= 0:
        ez = pow(2.718281828459045, -z)
        return 1.0 / (1.0 + ez)
    else:
        ez = pow(2.718281828459045, z)
        return ez / (1.0 + ez)


def _logit(p: float, eps: float = 1e-12) -> float:
    p = _clip(p, eps, 1.0 - eps)
    return math.log(p / (1.0 - p))


# -------------------- Platt scaling --------------------

import math

@dataclass
class _PlattModel:
    a: float
    b: float
    bias_only: bool = False  # when degenerate, use p=const
    const_p: float = 0.5

    def predict(self, p_raw: float) -> float:
        if self.bias_only:
            return _clip(self.const_p, 0.0, 1.0)
        z = _logit(_clip(float(p_raw), 1e-12, 1.0 - 1e-12))
        return _clip(_sigmoid(self.a * z + self.b), 0.0, 1.0)


class PlattCalibrator:
    """Logistic calibration using Newton–Raphson on cross-entropy.

    We fit a and b such that p = sigmoid(a * logit(p_raw) + b) best predicts labels.
    A small ridge (lambda_) stabilizes the Hessian.
    """

    def __init__(self, *, lambda_: float = 1e-3, max_iter: int = 100, tol: float = 1e-9) -> None:
        self.lambda_ = float(lambda_)
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self._model: Optional[_PlattModel] = None

    def fit(self, p_raw: Sequence[float], y: Sequence[int]) -> None:
        if len(p_raw) != len(y) or len(y) == 0:
            raise ValueError("length mismatch or empty data")
        # Check degeneracy (all zeros or ones)
        pos = sum(1 for t in y if int(t) == 1)
        neg = len(y) - pos
        if pos == 0 or neg == 0:
            # Degenerate — use constant calibrator equal to empirical mean
            mean_p = pos / max(1, len(y))
            self._model = _PlattModel(a=0.0, b=0.0, bias_only=True, const_p=mean_p)
            return

        # Initialize with a=1, b=logit(mean) - biased start to center outputs
        mean = pos / len(y)
        a, b = 1.0, _logit(_clip(mean, 1e-6, 1 - 1e-6))

        # Newton–Raphson iterations
        for _ in range(self.max_iter):
            g_a = g_b = 0.0
            h_aa = h_bb = 0.0
            h_ab = 0.0
            ll = 0.0
            for pi, yi in zip(p_raw, y):
                zi = _logit(_clip(float(pi), 1e-12, 1.0 - 1e-12))
                ti = int(yi)
                s = a * zi + b
                qi = _sigmoid(s)
                # gradient of logloss wrt a,b
                diff = qi - ti
                g_a += diff * zi
                g_b += diff
                # Hessian (second derivatives)
                w = qi * (1.0 - qi)
                h_aa += w * zi * zi
                h_bb += w
                h_ab += w * zi
                # logloss (for monitoring)
                ll -= ti * math.log(_clip(qi, 1e-15, 1.0)) + (1 - ti) * math.log(_clip(1.0 - qi, 1e-15, 1.0))

            # Ridge regularization on a,b
            g_a += self.lambda_ * a
            g_b += self.lambda_ * b
            h_aa += self.lambda_
            h_bb += self.lambda_

            # Solve 2x2 system
            det = h_aa * h_bb - h_ab * h_ab
            if det <= 1e-18:
                break  # ill-conditioned; stop early
            da = -(h_bb * g_a - h_ab * g_b) / det
            db = -(-h_ab * g_a + h_aa * g_b) / det

            a_new = a + da
            b_new = b + db
            if abs(da) + abs(db) < self.tol:
                a, b = a_new, b_new
                break
            a, b = a_new, b_new

        self._model = _PlattModel(a=float(a), b=float(b))

    def calibrate_prob(self, p_raw: float) -> float:
        if self._model is None:
            raise ValueError("PlattCalibrator not fitted")
        return self._model.predict(p_raw)

    # Sklearn-like convenience
    def fit_transform(self, p_raw: Sequence[float], y: Sequence[int]) -> List[float]:
        self.fit(p_raw, y)
        return [self.calibrate_prob(p) for p in p_raw]


# -------------------- Isotonic regression (PAVA) --------------------

@dataclass
class _IsoBlock:
    x_sum: float
    y_sum: float
    n: int

    @property
    def x_mean(self) -> float:
        return self.x_sum / self.n

    @property
    def y_mean(self) -> float:
        return self.y_sum / self.n


class IsotonicCalibrator:
    """Monotone non-decreasing calibration via PAVA.

    Fit on pairs (z_i, y_i) where z_i is a scalar score or probability.
    Inference returns a right-constant step function value at given z.
    """

    def __init__(self) -> None:
        self._xs: List[float] = []  # breakpoints (sorted)
        self._ys: List[float] = []  # fitted values (non-decreasing)
        self._fitted: bool = False

    def fit(self, z: Sequence[float], y: Sequence[int]) -> None:
        if len(z) != len(y) or len(y) == 0:
            raise ValueError("length mismatch or empty data")
        # Sort by z (ascending)
        data = sorted((float(zi), int(t)) for zi, t in zip(z, y))
        blocks: List[_IsoBlock] = []
        for xi, ti in data:
            blocks.append(_IsoBlock(x_sum=xi, y_sum=ti, n=1))
            # pool adjacent violators: ensure non-decreasing y_mean
            while len(blocks) >= 2 and blocks[-2].y_mean > blocks[-1].y_mean:
                b2 = blocks.pop()
                b1 = blocks.pop()
                blocks.append(_IsoBlock(
                    x_sum=b1.x_sum + b2.x_sum,
                    y_sum=b1.y_sum + b2.y_sum,
                    n=b1.n + b2.n,
                ))
        # Build step function: breakpoints at cumulative x means; predictions are block y means
        self._xs = []
        self._ys = []
        for b in blocks:
            self._xs.append(b.x_mean)
            self._ys.append(_clip(b.y_mean, 0.0, 1.0))
        # Ensure strictly increasing xs (if equal, keep last)
        xs2: List[float] = []
        ys2: List[float] = []
        for x, yv in zip(self._xs, self._ys):
            if xs2 and x <= xs2[-1]:
                xs2[-1] = x  # update to latest x (same block mean); yv is non-decreasing so overwrite ok
                ys2[-1] = yv
            else:
                xs2.append(x)
                ys2.append(yv)
        self._xs, self._ys = xs2, ys2
        self._fitted = True

    def calibrate(self, z: float) -> float:
        if not self._fitted:
            raise ValueError("IsotonicCalibrator not fitted")
        x = float(z)
        # right-constant step: find rightmost idx with xs[idx] <= x
        lo, hi = 0, len(self._xs) - 1
        if x <= self._xs[0]:
            return self._ys[0]
        if x >= self._xs[-1]:
            return self._ys[-1]
        while lo <= hi:
            mid = (lo + hi) // 2
            if self._xs[mid] <= x:
                lo = mid + 1
            else:
                hi = mid - 1
        return self._ys[hi]

    # convenience wrappers for prob-based interface
    def calibrate_prob(self, p_raw: float) -> float:
        return self.calibrate(p_raw)

    def fit_transform(self, z: Sequence[float], y: Sequence[int]) -> List[float]:
        self.fit(z, y)
        return [self.calibrate(v) for v in z]


# -------------------- Unified interface --------------------

class ProbabilityCalibrator:
    """Facade over Platt/Isotonic with a unified API.

    method: 'platt' or 'isotonic'
    input: expects probabilities p_raw \in (0,1)
    """

    def __init__(self, method: str = "isotonic") -> None:
        m = method.lower()
        if m not in ("platt", "isotonic"):
            raise ValueError("unknown calibration method: " + method)
        self._method = m
        self._platt: Optional[PlattCalibrator] = None
        self._iso: Optional[IsotonicCalibrator] = None

    def fit(self, p_raw: Sequence[float], y: Sequence[int]) -> None:
        if self._method == "platt":
            self._platt = PlattCalibrator()
            self._platt.fit(p_raw, y)
        else:
            self._iso = IsotonicCalibrator()
            self._iso.fit(p_raw, y)

    def calibrate_prob(self, p_raw: float) -> float:
        if self._method == "platt":
            if self._platt is None:
                raise ValueError("Platt calibrator not fitted")
            return self._platt.calibrate_prob(p_raw)
        else:
            if self._iso is None:
                raise ValueError("Isotonic calibrator not fitted")
            return self._iso.calibrate_prob(p_raw)

    # Aliases for compatibility with score.py
    def transform(self, p_raw: float) -> float:
        return self.calibrate_prob(p_raw)

    def predict_proba(self, p_raw: float) -> float:
        return self.calibrate_prob(p_raw)


# -------------------- Prequential metrics --------------------

@dataclass
class PrequentialMetrics:
    bins: int = 10
    # internal accumulators
    n: int = 0
    sum_brier: float = 0.0
    sum_logloss: float = 0.0

    def __post_init__(self) -> None:
        b = int(self.bins)
        if b <= 0:
            b = 10
        self.bins = b
        self._bin_n = [0] * b
        self._bin_p = [0.0] * b
        self._bin_y = [0.0] * b

    def update(self, p: float, y: int) -> None:
        p = _clip(float(p), 1e-12, 1.0 - 1e-12)
        yb = 1 if int(y) == 1 else 0
        self.n += 1
        self.sum_brier += (p - yb) ** 2
        self.sum_logloss += -(yb * math.log(p) + (1 - yb) * math.log(1.0 - p))
        # bin index by equal-width partition of [0,1)
        idx = min(int(p * self.bins), self.bins - 1)
        self._bin_n[idx] += 1
        self._bin_p[idx] += p
        self._bin_y[idx] += yb

    # aggregate metrics
    def brier(self) -> float:
        return self.sum_brier / max(1, self.n)

    def logloss(self) -> float:
        return self.sum_logloss / max(1, self.n)

    def ece(self) -> float:
        # Expected Calibration Error (L1 version)
        N = max(1, self.n)
        e = 0.0
        for n, sp, sy in zip(self._bin_n, self._bin_p, self._bin_y):
            if n == 0:
                continue
            conf = sp / n
            acc = sy / n
            e += (n / N) * abs(acc - conf)
        return e

    # diagnostics
    def bins_summary(self) -> List[Tuple[float, float, int]]:
        """Return list of (confidence, accuracy, count) per non-empty bin."""
        out = []
        for n, sp, sy in zip(self._bin_n, self._bin_p, self._bin_y):
            if n == 0:
                continue
            out.append((sp / n, sy / n, n))
        return out
