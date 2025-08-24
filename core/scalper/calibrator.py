from __future__ import annotations

"""
COPILOT_PROMPT:
Implement IsotonicCalibrator with fit/predict_p/e_pi_bps.
- Keep p in [0,1], monotonic vs score.
- Fallback to Platt sigmoid if isotonic not available.
- Provide thorough docstrings and type hints.
- Add logging via structlog: event name 'calibrator.entry'.
"""

from dataclasses import dataclass
from typing import Protocol

import numpy as np
import structlog

try:  # optional
    from sklearn.isotonic import IsotonicRegression
except Exception:  # pragma: no cover - sklearn may be missing
    IsotonicRegression = None  # type: ignore


logger = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CalibInput:
    score: float
    a_bps: float
    b_bps: float
    fees_bps: float
    slip_bps: float
    regime: str


@dataclass(frozen=True)
class CalibOutput:
    p_tp: float
    e_pi_bps: float


class Calibrator(Protocol):
    def fit(self, scores: np.ndarray, y: np.ndarray) -> None: ...
    def predict_p(self, score: float) -> float: ...
    def e_pi_bps(self, ci: CalibInput) -> CalibOutput: ...


class IsotonicCalibrator:
    """Isotonic regression calibrator with Platt fallback.

    If scikit-learn is unavailable, falls back to a sigmoid with k=2.0.
    """

    def __init__(self) -> None:
        self._iso = IsotonicRegression(out_of_bounds="clip") if IsotonicRegression else None
        self._platt_k = 2.0
        # If we use isotonic, we'll fit on domain [-1,1]
        self._fitted = False

    def fit(self, scores: np.ndarray, y: np.ndarray) -> None:
        scores = np.asarray(scores, dtype=float)
        y = np.asarray(y, dtype=float)
        mask = np.isfinite(scores) & np.isfinite(y)
        scores = scores[mask]
        y = y[mask]
        if scores.size == 0:
            self._fitted = False
            return
        if self._iso is not None:
            xs = np.clip(scores, -1.0, 1.0)
            ys = np.clip(y, 0.0, 1.0)
            self._iso.fit(xs, ys)
            self._fitted = True
        else:
            # Platt fallback has no fit (fixed slope), could estimate k but keep simple
            self._fitted = True

    def predict_p(self, score: float) -> float:
        if not self._fitted:
            # Fallback sigmoid
            p = 1.0 / (1.0 + np.exp(-self._platt_k * float(score)))
            return float(np.clip(p, 0.0, 1.0))
        if self._iso is not None:
            xs = float(np.clip(score, -1.0, 1.0))
            p = float(self._iso.predict([xs])[0])
            return float(np.clip(p, 0.0, 1.0))
        # Fallback
        p = 1.0 / (1.0 + np.exp(-self._platt_k * float(score)))
        return float(np.clip(p, 0.0, 1.0))

    def e_pi_bps(self, ci: CalibInput) -> CalibOutput:
        p = self.predict_p(ci.score)
        a = float(ci.a_bps)
        b = float(ci.b_bps)
        fees_slip = float(ci.fees_bps + ci.slip_bps)
        e_pi = p * b - (1.0 - p) * a - fees_slip
        logger.info(
            "calibrator.entry",
            score=ci.score,
            p_tp=p,
            e_pi_bps=e_pi,
            a_bps=a,
            b_bps=b,
            fees_bps=float(ci.fees_bps),
            slip_bps=float(ci.slip_bps),
            regime=ci.regime,
        )
        return CalibOutput(p_tp=float(np.clip(p, 0.0, 1.0)), e_pi_bps=float(e_pi))
