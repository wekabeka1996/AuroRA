import math
import numpy as np
import pytest
from living_latent.core.acceptance import Acceptance, AcceptanceCfg, Event

SEED = 1337
rng = np.random.default_rng(SEED)

def make_cfg():
    return AcceptanceCfg(
        tau_pass=0.75,
        tau_derisk=0.50,
        coverage_lower_bound=0.90,
        surprisal_p95_guard=2.5,
        latency_p95_max_ms=120.0,
        max_interval_rel_width=0.06,
        persistence_n=20,
        penalties={
            "latency_to_kappa_bonus": -0.05,
            "coverage_deficit_bonus": -0.10,
        },
        c_ref=0.01, beta_ref=0.0, sigma_min=1e-6
    )

def test_kappa_monotonic_width():
    cfg = make_cfg()
    acc = Acceptance(cfg)
    mu, sigma = 100.0, 10.0
    widths = np.array([0.2, 0.5, 1.0, 2.0, 4.0])
    kappas = []
    for w_rel in widths:
        width = w_rel * max(1.0, abs(mu))
        lo, hi = mu - width/2, mu + width/2
        evt = Event(ts=0.0, mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=10.0, y=None)
        decision, info = acc.decide(evt)
        kappas.append(info["kappa"])
    assert all(kappas[i] >= kappas[i+1] for i in range(len(kappas)-1))

def test_surprisal_p95_guard_triggers_derisk():
    cfg = make_cfg()
    acc = Acceptance(cfg)
    mu, sigma = 0.0, 1.0
    for t in range(200):
        width = 0.5
        lo, hi = mu - width/2, mu + width/2
        y = mu + (4.0 if t % 10 == 0 else rng.normal(0, 0.5))
        evt = Event(ts=float(t), mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=50.0, y=y)
        acc.update(evt)
    evt2 = Event(ts=201.0, mu=mu, sigma=sigma, interval=(-0.25, 0.25), latency_ms=50.0, y=None)
    decision, info = acc.decide(evt2)
    assert float(info["p95_surprisal"]) > cfg.surprisal_p95_guard
    assert decision in ("DERISK", "BLOCK")

def test_latency_guard_derisks():
    cfg = make_cfg()
    acc = Acceptance(cfg)
    mu, sigma = 10.0, 1.0
    lo, hi = 9.9, 10.1
    for t in range(100):
        evt = Event(ts=float(t), mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=300.0, y=mu)
        acc.update(evt)
    evt2 = Event(ts=101.0, mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=10.0, y=None)
    decision, info = acc.decide(evt2)
    assert float(info["latency_p95"]) > cfg.latency_p95_max_ms
    assert decision in ("DERISK", "BLOCK")

def test_coverage_streak_blocks():
    cfg = make_cfg()
    acc = Acceptance(cfg)
    mu, sigma = 0.0, 1.0
    width = 0.1
    lo, hi = mu - width/2, mu + width/2
    for t in range(cfg.persistence_n + 5):
        y = 5.0
        evt = Event(ts=float(t), mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=10.0, y=y)
        acc.update(evt)
    evt2 = Event(ts=999.0, mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=10.0, y=None)
    decision, info = acc.decide(evt2)
    assert decision == "BLOCK"
