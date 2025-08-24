from math import log

import pytest

from core.scalper.sprt import SPRT, SprtConfig, thresholds_from_alpha_beta


def test_thresholds_from_alpha_beta_matches_formula():
    alpha, beta = 0.05, 0.2
    A, B = thresholds_from_alpha_beta(alpha, beta)
    assert pytest.approx(A, rel=1e-9) == log((1 - beta) / alpha)
    assert pytest.approx(B, rel=1e-9) == log(beta / (1 - alpha))


def test_sprt_accepts_when_samples_near_mu1():
    cfg = SprtConfig(mu0=0.0, mu1=1.0, sigma=1.0, A=2.0, B=-2.0, max_obs=50)
    sprt = SPRT(cfg)
    xs = [1.0] * 20
    decision = sprt.run(xs)
    assert decision in {"ACCEPT", "CONTINUE"}
    # If it continued, push a few more
    if decision == "CONTINUE":
        for _ in range(10):
            decision = sprt.update(1.0)
            if decision != "CONTINUE":
                break
    assert decision == "ACCEPT"


def test_sprt_rejects_when_samples_near_mu0():
    cfg = SprtConfig(mu0=0.0, mu1=1.0, sigma=1.0, A=2.0, B=-2.0, max_obs=50)
    sprt = SPRT(cfg)
    xs = [0.0] * 50
    decision = sprt.run(xs)
    assert decision == "REJECT"


def test_sprt_timeout_returns_continue():
    # Set extremely wide thresholds so decision won't be reached quickly, forcing timeout path
    cfg = SprtConfig(mu0=0.0, mu1=0.5, sigma=1.0, A=1e9, B=-1e9, max_obs=1_000_000)
    sprt = SPRT(cfg)
    xs = [0.1] * 100_000
    decision = sprt.run_with_timeout(xs, time_limit_ms=0.0)
    assert decision == "CONTINUE"
