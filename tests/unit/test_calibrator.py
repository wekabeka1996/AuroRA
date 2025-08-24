from __future__ import annotations

import numpy as np

from core.scalper.calibrator import CalibInput, IsotonicCalibrator


def test_calibrator_monotonic_and_e_pi():
    cal = IsotonicCalibrator()
    # Synthetic monotone relation
    xs = np.linspace(-1, 1, 11)
    ys = (xs + 1) / 2  # maps -1->0, +1->1
    cal.fit(xs, ys)

    p_low = cal.predict_p(-0.8)
    p_mid = cal.predict_p(0.0)
    p_hi = cal.predict_p(0.8)
    assert 0.0 <= p_low <= p_mid <= p_hi <= 1.0

    ci = CalibInput(score=0.2, a_bps=8.0, b_bps=12.0, fees_bps=1.0, slip_bps=2.0, regime="normal")
    out = cal.e_pi_bps(ci)
    # e_pi can be negative or positive; check numeric stability and clipping of p
    assert 0.0 <= out.p_tp <= 1.0
    assert isinstance(out.e_pi_bps, float)
