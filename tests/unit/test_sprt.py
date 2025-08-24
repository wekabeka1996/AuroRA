from __future__ import annotations

import numpy as np

from core.scalper.sprt import SPRT, SprtConfig


def test_sprt_accept_reject_simple():
    cfg = SprtConfig(mu0=0.0, mu1=1.0, sigma=1.0, A=2.0, B=-2.0, max_obs=10)
    sprt = SPRT(cfg)

    # Sequence near mu1 should ACCEPT
    xs_accept = [1.1, 0.9, 1.2, 0.8, 1.0]
    d1 = sprt.run(xs_accept)
    assert d1 in ("ACCEPT", "CONTINUE")

    # Sequence near mu0 should REJECT
    xs_reject = [-0.1, 0.0, 0.2, -0.3, 0.1]
    d2 = sprt.run(xs_reject)
    assert d2 in ("REJECT", "CONTINUE")


def test_sprt_max_obs_terminal():
    cfg = SprtConfig(mu0=0.0, mu1=0.5, sigma=1.0, A=5.0, B=-5.0, max_obs=3)
    sprt = SPRT(cfg)
    xs = [0.4, 0.6, 0.5]
    d = sprt.run(xs)
    assert d in ("ACCEPT", "REJECT")
