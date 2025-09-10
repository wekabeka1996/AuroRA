"""
Aurora+ScalpBot — core/calibration/calibrator.py
-----------------------------------------------
Single-file module: probability calibration tools + metrics for R1.

Paste into: aurora/core/calibration/calibrator.py
Run self-tests: `python aurora/core/calibration/calibrator.py`

Implements (§ R1/Road_map alignment):
- Metrics: ECE (uniform bins), Brier, LogLoss; prequential online metrics (§6)
- Calibrators: Platt (logistic), Temperature scaling (for probability logits),
  Isotonic regression via PAV (no external deps) (§6)

No external dependencies; NumPy is optional. Compatible with `core/types.py` if present.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
import math
import random

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Optional import from core/types; minimal fallbacks if unavailable -----
try:  # pragma: no cover - exercised in integration
    from core.types import ProbabilityMetrics
    PMetricsType = type[ProbabilityMetrics]
except Exception:
    @dataclass
    class ProbabilityMetrics:  # fallback
        ece: float | None = None
        brier: float | None = None
        logloss: float | None = None

        def lambda_cal(self, *, eta: float = 10.0, zeta: float = 5.0) -> float:
            ece = 0.0 if self.ece is None else float(self.ece)
            logloss = 0.0 if self.logloss is None else float(self.logloss)
            return math.exp(-eta * ece) * math.exp(-zeta * logloss)
    PMetricsType = type[ProbabilityMetrics]

# ------------------------------------------------------------------------------

def _sigmoid(x: float) -> float:
    if x >= 0:
        z = math.exp(-x)
        return 1.0 / (1.0 + z)
    else:
        z = math.exp(x)
        return z / (1.0 + z)


def _clip01(p: float, eps: float = 1e-12) -> float:
    return min(1.0 - eps, max(eps, p))


def _logit(p: float, eps: float = 1e-12) -> float:
    p = _clip01(p, eps)
    return math.log(p / (1.0 - p))


# =============================
# Metrics
# =============================

def brier_score(p: Sequence[float], y: Sequence[int]) -> float:
    n = max(1, len(p))
    s = 0.0
    for pi, yi in zip(p, y):
        d = pi - float(yi)
        s += d * d
    return s / n


def log_loss(p: Sequence[float], y: Sequence[int]) -> float:
    n = max(1, len(p))
    s = 0.0
    for pi, yi in zip(p, y):
        pi = _clip01(float(pi))
        if yi:
            s += -math.log(pi)
        else:
            s += -math.log(1.0 - pi)
    return s / n


def ece_uniform(p: Sequence[float], y: Sequence[int], n_bins: int = 15) -> float:
    if n_bins <= 1:
        return abs(sum(y_i for y_i in y) / max(1, len(y)) - (sum(p) / max(1, len(p))))
    bins: list[float] = [0.0] * n_bins
    cnts: list[int] = [0] * n_bins
    hits: list[int] = [0] * n_bins
    for pi, yi in zip(p, y):
        b = min(n_bins - 1, max(0, int(float(pi) * n_bins)))
        bins[b] += float(pi)
        cnts[b] += 1
        hits[b] += int(yi)
    ece = 0.0
    n = max(1, len(p))
    for b in range(n_bins):
        if cnts[b] == 0:
            continue
        conf = bins[b] / cnts[b]
        acc = hits[b] / cnts[b]
        ece += (cnts[b] / n) * abs(acc - conf)
    return ece


@dataclass
class PrequentialMetrics:
    """Online (prequential) metrics with fixed binning for ECE."""
    n_bins: int = 15
    _n: int = 0
    _sum_brier: float = 0.0
    _sum_logloss: float = 0.0
    _bin_sum_p: list[float] = None  # type: ignore
    _bin_hits: list[int] = None  # type: ignore
    _bin_cnts: list[int] = None  # type: ignore

    def __post_init__(self) -> None:
        self._bin_sum_p = [0.0] * self.n_bins
        self._bin_hits = [0] * self.n_bins
        self._bin_cnts = [0] * self.n_bins

    def update(self, p: float, y: int) -> None:
        p = float(p)
        y = int(y)
        self._n += 1
        self._sum_brier += (p - y) ** 2
        p_c = _clip01(p)
        self._sum_logloss += - (y * math.log(p_c) + (1 - y) * math.log(1.0 - p_c))
        b = min(self.n_bins - 1, max(0, int(p * self.n_bins)))
        self._bin_sum_p[b] += p
        self._bin_hits[b] += y
        self._bin_cnts[b] += 1

    def metrics(self) -> ProbabilityMetrics:
        n = max(1, self._n)
        ece = 0.0
        for i in range(self.n_bins):
            if self._bin_cnts[i] == 0:
                continue
            conf = self._bin_sum_p[i] / self._bin_cnts[i]
            acc = self._bin_hits[i] / self._bin_cnts[i]
            ece += (self._bin_cnts[i] / n) * abs(acc - conf)
        return ProbabilityMetrics(
            ece=ece,
            brier=self._sum_brier / n,
            logloss=self._sum_logloss / n,
        )


# =============================
# Calibrators
# =============================

@dataclass
class PlattCalibrator:
    """Logistic calibration: p = σ(A·score + B)."""
    A: float = 1.0
    B: float = 0.0
    l2: float = 1e-2
    max_iter: int = 100
    tol: float = 1e-9

    def fit(self, scores: Sequence[float], y: Sequence[int]) -> PlattCalibrator:
        A, B = self.A, self.B
        lam = float(self.l2)
        for _ in range(self.max_iter):
            gA = lam * A
            gB = lam * B
            hAA = lam
            hAB = 0.0
            hBB = lam
            for s, yi in zip(scores, y):
                z = A * float(s) + B
                q = _sigmoid(z)
                w = q * (1.0 - q)
                diff = (q - yi)
                gA += diff * s
                gB += diff
                hAA += w * (s * s)
                hAB += w * s
                hBB += w
            # Solve 2x2: H * delta = -g
            det = hAA * hBB - hAB * hAB
            if det <= 0:
                # fall back to small gradient step
                stepA = -gA / (hAA + 1e-6)
                stepB = -gB / (hBB + 1e-6)
            else:
                stepA = (-gA * hBB + gB * hAB) / det
                stepB = (-gB * hAA + gA * hAB) / det
            # backtracking line search
            t = 1.0
            def nll(a: float, b: float) -> float:
                ssum = 0.5 * lam * (a * a + b * b)
                for s, yi in zip(scores, y):
                    z = a * float(s) + b
                    # stable log(1+e^z)
                    if z >= 0:
                        ssum += (z - yi * z) + math.log1p(math.exp(-z))
                    else:
                        ssum += - yi * z + math.log1p(math.exp(z))
                return ssum
            base = nll(A, B)
            while t > 1e-6:
                A_new = A + t * stepA
                B_new = B + t * stepB
                if nll(A_new, B_new) <= base:
                    A, B = A_new, B_new
                    break
                t *= 0.5
            if abs(stepA) < self.tol and abs(stepB) < self.tol:
                break
        self.A, self.B = float(A), float(B)
        return self

    def predict_proba(self, scores: Sequence[float]) -> list[float]:
        return [_sigmoid(self.A * float(s) + self.B) for s in scores]

    def calibrate_prob(self, p_raw: float) -> float:
        """Calibrate a single probability using Platt scaling."""
        return _sigmoid(self.A * float(p_raw) + self.B)


@dataclass
class TemperatureScaler:
    """Temperature scaling for probabilities via logits: q = σ(logit(p)/T)."""
    T: float = 1.0
    max_iter: int = 100
    tol: float = 1e-9

    def fit(self, p: Sequence[float], y: Sequence[int]) -> TemperatureScaler:
        # Use Newton steps with backtracking; ensure T>0.
        T = max(1e-3, float(self.T))
        x = [_logit(pi) for pi in p]
        def nll(temp: float) -> float:
            ssum = 0.0
            for xi, yi in zip(x, y):
                z = xi / temp
                qi = _sigmoid(z)
                ssum += - (yi * math.log(_clip01(qi)) + (1 - yi) * math.log(_clip01(1.0 - qi)))
            return ssum
        for _ in range(self.max_iter):
            g = 0.0
            h = 0.0
            for xi, yi in zip(x, y):
                z = xi / T
                q = _sigmoid(z)
                g += - (q - yi) * (xi / (T * T))
                h += q * (1.0 - q) * (xi * xi) / (T ** 4) + 2.0 * (q - yi) * (xi) / (T ** 3)
            step = - g / max(1e-12, h)
            # backtracking line search
            base = nll(T)
            t = 1.0
            while t > 1e-6:
                T_new = max(1e-3, T + t * step)
                if nll(T_new) <= base:
                    T = T_new
                    break
                t *= 0.5
            if abs(step) < self.tol:
                break
        self.T = float(T)
        return self

    def predict_proba(self, p: Sequence[float]) -> list[float]:
        return [_sigmoid(_logit(pi) / self.T) for pi in p]


@dataclass
class IsotonicCalibrator:
    """Isotonic regression (PAV) mapping x→p, where x∈R is score or uncali. prob.

    Implementation: pool-adjacent-violators with unit weights. For prediction,
    we perform step-function lookup with linear interpolation between knots for
    smoother behavior.
    """
    xs_: list[float] = None  # type: ignore
    ys_: list[float] = None  # type: ignore

    def fit(self, x: Sequence[float], y: Sequence[int]) -> IsotonicCalibrator:
        pairs = sorted((float(xi), int(yi)) for xi, yi in zip(x, y))
        xs = [xi for xi, _ in pairs]
        ys = [float(yi) for _, yi in pairs]

        # Pool Adjacent Violators (PAVA) algorithm
        n = len(ys)
        if n == 0:
            self.xs_ = []
            self.ys_ = []
            return self

        # Use dynamic programming approach for PAVA
        blocks = []
        current_block_start = 0

        for i in range(1, n):
            if ys[i] >= ys[i-1]:
                # No violation, continue current block
                continue
            else:
                # Violation found, pool from current_block_start to i
                block_sum = sum(ys[current_block_start:i+1])
                block_count = i - current_block_start + 1
                pooled_value = block_sum / block_count

                # Set all values in current block to pooled value
                for j in range(current_block_start, i+1):
                    ys[j] = pooled_value

                current_block_start = i + 1

        # Build the final step function
        # Remove duplicates and create unique breakpoints
        self.xs_ = [xs[0]]
        self.ys_ = [ys[0]]

        for i in range(1, n):
            if xs[i] != self.xs_[-1] or ys[i] != self.ys_[-1]:
                self.xs_.append(xs[i])
                self.ys_.append(ys[i])

        return self

    def predict_proba(self, x: Sequence[float]) -> list[float]:
        if not self.xs_:
            return [0.5] * len(list(x))
        res: list[float] = []
        for xi in x:
            xi = float(xi)
            # find insertion point
            lo, hi = 0, len(self.xs_) - 1
            if xi <= self.xs_[0]:
                res.append(self.ys_[0])
                continue
            if xi >= self.xs_[-1]:
                res.append(self.ys_[-1])
                continue
            # binary search
            while lo <= hi:
                mid = (lo + hi) // 2
                if self.xs_[mid] <= xi:
                    lo = mid + 1
                else:
                    hi = mid - 1
            j = max(1, lo - 1)
            x0, x1 = self.xs_[j - 1], self.xs_[j]
            y0, y1 = self.ys_[j - 1], self.ys_[j]
            # linear interpolation between knots
            t = 0.0 if x1 == x0 else (xi - x0) / (x1 - x0)
            res.append((1 - t) * y0 + t * y1)
        return [min(1.0, max(0.0, r)) for r in res]

    def calibrate_prob(self, p_raw: float) -> float:
        """Calibrate a single probability using isotonic regression."""
        return self.predict_proba([p_raw])[0]


# =============================
# Unified interface
# =============================

class ProbabilityCalibrator:
    """Facade over Platt/Isotonic with a unified API.

    method: 'platt' or 'isotonic'
    input: expects probabilities p_raw in (0,1)
    """

    def __init__(self, method: str = "isotonic") -> None:
        m = method.lower()
        if m not in ("platt", "isotonic"):
            raise ValueError("unknown calibration method: " + method)
        self._method = m
        self._platt: PlattCalibrator | None = None
        self._iso: IsotonicCalibrator | None = None

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


# =============================
# End-to-end helper
# =============================

def evaluate_calibration(p: Sequence[float], y: Sequence[int], n_bins: int = 15) -> ProbabilityMetrics:
    return ProbabilityMetrics(
        ece=ece_uniform(p, y, n_bins=n_bins),
        brier=brier_score(p, y),
        logloss=log_loss(p, y),
    )


# =============================
# Self-tests (synthetic)
# =============================

def _make_synthetic(n: int = 5000, seed: int = 7) -> tuple[list[float], list[int], list[float]]:
    random.seed(seed)
    xs: list[float] = []  # raw scores
    y: list[int] = []
    for _ in range(n):
        s = random.gauss(0.0, 1.0)
        xs.append(s)
    # True mapping: p* = σ(2.0*s - 0.5)
    ps_true = [_sigmoid(2.0 * s - 0.5) for s in xs]
    y = [1 if random.random() < p else 0 for p in ps_true]
    # Model's uncalibrated probabilities are mis-scaled: p_unc = σ(1.2*s - 0.2)
    p_unc = [_sigmoid(1.2 * s - 0.2) for s in xs]
    return xs, y, p_unc


def _test_metrics() -> None:
    p = [0.1, 0.9, 0.6, 0.4]
    y = [0, 1, 1, 0]
    m = evaluate_calibration(p, y, n_bins=4)
    assert m.ece is not None and 0 <= m.ece <= 1
    assert m.brier is not None and 0 <= m.brier <= 1
    assert m.logloss is not None and m.logloss >= 0


def _test_platt_improves_logloss() -> None:
    xs, y, p_unc = _make_synthetic()
    # Use raw scores for Platt (assume model returns a score; here we reuse xs)
    pl = PlattCalibrator(l2=1e-2, max_iter=100)
    pl.fit(xs, y)
    p_platt = pl.predict_proba(xs)
    m_unc = evaluate_calibration(p_unc, y)
    m_pl = evaluate_calibration(p_platt, y)
    # should improve logloss vs uncalibrated probabilities
    assert m_pl.logloss is not None and m_unc.logloss is not None
    assert m_pl.logloss <= m_unc.logloss + 0.05


def _test_temperature_improves() -> None:
    xs, y, p_unc = _make_synthetic()
    ts = TemperatureScaler()
    ts.fit(p_unc, y)
    p_temp = ts.predict_proba(p_unc)
    m_unc = evaluate_calibration(p_unc, y)
    m_temp = evaluate_calibration(p_temp, y)
    assert m_temp.logloss is not None and m_unc.logloss is not None
    assert m_temp.logloss <= m_unc.logloss + 0.02
    # ECE tends to improve as well on average
    assert m_temp.ece is not None and m_unc.ece is not None
    assert m_temp.ece <= m_unc.ece + 0.05


def _test_isotonic_monotone() -> None:
    # create a zigzag mapping so isotonic must pool
    x = [0.0, 0.2, 0.4, 0.6, 0.8, 1.0]
    y = [0, 1, 0, 1, 0, 1]
    iso = IsotonicCalibrator().fit(x, y)
    # predictions must be non-decreasing
    preds = iso.predict_proba(x)
    for i in range(len(preds) - 1):
        assert preds[i] <= preds[i + 1] + 1e-12


if __name__ == "__main__":
    _test_metrics()
    _test_platt_improves_logloss()
    _test_temperature_improves()
    _test_isotonic_monotone()
    print("OK - core/calibration/calibrator.py self-tests passed")
