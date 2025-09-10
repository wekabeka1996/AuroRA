"""
Aurora+ScalpBot — repo/core/calibration/drift.py
-------------------------------------------------
Streaming drift detectors on **logit** (or score) series used for calibration
monitoring: two-sided CUSUM and Gaussian GLR over a rolling window.

Paste into: repo/core/calibration/drift.py
Run self-tests: `python repo/core/calibration/drift.py`

Implements (per project structure):
- CUSUMDetector: Page's CUSUM with reference k and threshold h (two-sided)
- GLRDetector: max log-likelihood ratio for change-in-mean (unknown σ) within
  a rolling window; returns stat and alarm if above threshold
- DriftMonitor: combines both; convenient streaming API `update(logit, ts)`

INPUT SPECIFICATIONS:
- Input: logit/score series (dimensionless, event-time ordered)
- No look-ahead bias: detectors use only past observations
- Robustness: optional clipping prevents outlier influence
- Time series: assumes continuous monitoring with potential gaps

OUTPUT SPECIFICATIONS:
- cusum_pos/cusum_neg: cumulative sums for positive/negative deviations
- cusum_alarm: binary alarm (1.0 if either CUSUM exceeds threshold)
- glr_stat: maximum likelihood ratio statistic across window splits
- glr_alarm: binary alarm (1.0 if GLR exceeds threshold)
- drift_alarm: composite alarm (1.0 if either detector alarms)

CONFIGURATION:
Default thresholds (k=0.25, h=6.0, window=200, thr=25.0, clip=6.0) should be
calibrated on in-control periods. Move to configs/schema for SSOT compliance.

No external dependencies; NumPy optional. Standalone.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
import random

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

try:
    from common.events import EventEmitter
    _event_emitter = EventEmitter()
except ImportError:
    # Fallback if events module not available
    _event_emitter = None


# =============================
# CUSUM (two-sided)
# =============================

@dataclass
class CUSUMDetector:
    """Two-sided Page's CUSUM for shifts in mean of a stream x_t.

    Parameters
    ----------
    k : float
        Reference value (half the shift you want to be most sensitive to).
    h : float
        Decision threshold. Typical range: 4..8 times the std of in-control noise.
    clip : float
        Optional absolute clip for x to increase robustness.
    """
    k: float = 0.25
    h: float = 5.0
    clip: float | None = None

    s_pos: float = 0.0
    s_neg: float = 0.0
    last_ts: float | None = None

    def reset(self) -> None:
        self.s_pos = 0.0
        self.s_neg = 0.0
        self.last_ts = None

    def update(self, x: float, ts: float | None = None) -> dict[str, float]:
        if self.clip is not None:
            c = float(self.clip)
            x = max(-c, min(c, float(x)))
        else:
            x = float(x)
        # Page's recursion
        self.s_pos = max(0.0, self.s_pos + x - self.k)
        self.s_neg = min(0.0, self.s_neg + x + self.k)
        self.last_ts = None if ts is None else float(ts)
        alarm = 1.0 if (self.s_pos >= self.h or -self.s_neg >= self.h) else 0.0
        return {
            "cusum_pos": self.s_pos,
            "cusum_neg": self.s_neg,
            "cusum_alarm": alarm,
        }


# =============================
# GLR over rolling window (Gaussian, change in mean)
# =============================

@dataclass
class GLRDetector:
    """Generalized Likelihood Ratio for a change-in-mean within a rolling window.

    Assumes in-control: x_t ~ N(μ, σ²) with constant σ. Tests H0: no change vs H1:
    one change-point τ in the last W points. Uses the maximum standardized
    difference in sample means across splits (τ) as GLR stat.

    Threshold `thr` is on the squared standardized mean gap times an empirical
    factor. This is a pragmatic detector; for rigorous control consult Lorden/Page.
    """
    window: int = 200
    thr: float = 25.0  # typical 16..36 for unit-variance noise
    clip: float | None = 6.0

    def __post_init__(self) -> None:
        self.buf: deque[float] = deque()
        self.sum: float = 0.0
        self.sum2: float = 0.0

    def reset(self) -> None:
        self.buf.clear()
        self.sum = 0.0
        self.sum2 = 0.0

    def _push(self, x: float) -> None:
        if self.clip is not None:
            c = float(self.clip)
            x = max(-c, min(c, float(x)))
        else:
            x = float(x)
        self.buf.append(x)
        self.sum += x
        self.sum2 += x * x
        if len(self.buf) > self.window:
            y = self.buf.popleft()
            self.sum -= y
            self.sum2 -= y * y

    def _glr_stat(self) -> float:
        n = len(self.buf)
        if n < 2:
            return 0.0
        # estimate pooled variance
        mu = self.sum / n
        var = max(1e-9, self.sum2 / n - mu * mu)
        sd = math.sqrt(var)
        # try all split points τ (leave at least 1 point on each side)
        best = 0.0
        # precompute prefix sums
        s = 0.0
        k = 0
        for x in self.buf:
            k += 1
            if k == n:
                break
            s += x
            m1 = s / k
            m2 = (self.sum - s) / (n - k)
            gap = abs(m1 - m2) / max(1e-12, sd)
            stat = gap * gap * min(k, n - k)  # scaled by segment size
            if stat > best:
                best = stat
        return best

    def update(self, x: float, ts: float | None = None) -> dict[str, float]:
        self._push(x)
        g = self._glr_stat()
        alarm = 1.0 if g >= self.thr else 0.0
        return {"glr_stat": g, "glr_alarm": alarm}


# =============================
# Drift monitor (combo)
# =============================

@dataclass
class DriftMonitor:
    cusum: CUSUMDetector = field(default_factory=lambda: CUSUMDetector(k=0.25, h=6.0, clip=6.0))
    glr: GLRDetector = field(default_factory=lambda: GLRDetector(window=200, thr=25.0, clip=6.0))

    def reset(self) -> None:
        self.cusum.reset()
        self.glr.reset()

    def update(self, logit: float, ts: float | None = None) -> dict[str, float]:
        """Feed next logit/score and get combined drift diagnostics.

        Returns
        -------
        dict with keys: cusum_pos, cusum_neg, cusum_alarm, glr_stat, glr_alarm,
        and composite `drift_alarm` = 1 if either sub-alarm is 1.
        """
        out_c = self.cusum.update(logit, ts)
        out_g = self.glr.update(logit, ts)
        drift_alarm = 1.0 if (out_c["cusum_alarm"] > 0.5 or out_g["glr_alarm"] > 0.5) else 0.0

        # Emit ALERT_CALIBRATION_DRIFT event if drift detected
        if drift_alarm > 0.5 and _event_emitter is not None:
            event_data = {
                "timestamp": ts,
                "logit_value": logit,
                "cusum_pos": out_c["cusum_pos"],
                "cusum_neg": out_c["cusum_neg"],
                "cusum_alarm": out_c["cusum_alarm"],
                "glr_stat": out_g["glr_stat"],
                "glr_alarm": out_g["glr_alarm"],
                "drift_alarm": drift_alarm,
                "detector": "combined_cusum_glr"
            }
            _event_emitter.emit(
                type="ALERT_CALIBRATION_DRIFT",
                payload=event_data,
                severity="warning",
                code="ALERT_CALIBRATION_DRIFT"
            )

        out: dict[str, float] = {**out_c, **out_g}
        out["drift_alarm"] = drift_alarm
        return out


# =============================
# Self-tests (synthetic)
# =============================

def _make_logit_series(n: int = 600, mu0: float = 0.0, sigma: float = 1.0, shift_at: int = 300, dmu: float = 0.8, seed: int = 7) -> list[float]:
    rnd = random.Random(seed)
    xs: list[float] = []
    for t in range(n):
        m = mu0 + (dmu if t >= shift_at else 0.0)
        xs.append(rnd.gauss(m, sigma))
    return xs


def _test_cusum_and_glr_detect_shift() -> None:
    xs = _make_logit_series()
    dm = DriftMonitor(cusum=CUSUMDetector(k=0.25, h=6.0, clip=6.0), glr=GLRDetector(window=120, thr=20.0, clip=6.0))
    alarms = []
    for i, x in enumerate(xs):
        out = dm.update(x, ts=float(i))
        if out["drift_alarm"] > 0.5:
            alarms.append(i)
    # Must detect after the shift point within a reasonable delay
    assert any(i >= 300 and i <= 500 for i in alarms)


def _test_no_false_alarm_on_stationary() -> None:
    xs = _make_logit_series(dmu=0.0, n=400)  # shorter series, no shift
    dm = DriftMonitor(cusum=CUSUMDetector(k=0.5, h=12.0, clip=6.0), glr=GLRDetector(window=200, thr=50.0, clip=6.0))
    tripped = False
    for i, x in enumerate(xs):
        out = dm.update(x, ts=float(i))
        tripped = tripped or (out["drift_alarm"] > 0.5)
    # With very conservative thresholds, should not trip on stationary data
    assert not tripped


if __name__ == "__main__":
    _test_cusum_and_glr_detect_shift()
    _test_no_false_alarm_on_stationary()
    print("OK - repo/core/calibration/drift.py self-tests passed")
