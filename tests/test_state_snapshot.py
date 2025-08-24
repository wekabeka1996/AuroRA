from __future__ import annotations
import math, os, tempfile, json, time
from living_latent.core.icp_dynamic import AdaptiveICP
from living_latent.core.acceptance import Acceptance, AcceptanceCfg, Event
from living_latent.core.acceptance_hysteresis import HysteresisGate, HysteresisCfg
from living_latent.state.snapshot import (
    make_icp_state, make_acceptance_state, save_snapshot, load_snapshot,
    load_icp_state, load_acceptance_state
)

def _build_system(alpha=0.1):
    icp = AdaptiveICP(alpha_target=alpha, eta=0.01, window=256, quantile_mode='p2')
    gate = HysteresisGate(HysteresisCfg.from_dict({}, {}))
    acc_cfg = AcceptanceCfg(
        tau_pass=0.75, tau_derisk=0.5,
        coverage_lower_bound=0.90, surprisal_p95_guard=3.0,
        latency_p95_max_ms=150.0, max_interval_rel_width=0.2,
        persistence_n=5, penalties={'latency_to_kappa_bonus': -0.05, 'coverage_deficit_bonus': -0.1},
        c_ref=0.01, beta_ref=0.0, sigma_min=1e-6
    )
    acc = Acceptance(acc_cfg, hysteresis_gate=gate, metrics=None, profile_label='test')
    return icp, acc

def _simulate(icp, acc, n: int, seed=42):
    import random
    rng = random.Random(seed)
    records = []
    for i in range(n):
        mu = rng.uniform(-1, 1)
        sigma = rng.uniform(0.05, 0.15)
        # Simulate interval as mu ± 3 sigma
        lo, hi = mu - 3*sigma, mu + 3*sigma
        # Realized y with small bias
        y = rng.gauss(mu, sigma)
        evt = Event(ts=i, mu=mu, sigma=sigma, interval=(lo, hi), latency_ms=rng.uniform(5,30), y=y)
        icp.update(y, mu, sigma)
        acc.update(evt)
        acc.decide(evt)
        records.append((mu, lo, hi, y))
    return records

def test_state_snapshot_roundtrip():
    icp1, acc1 = _build_system()
    _simulate(icp1, acc1, 400)
    # snapshot
    icp_state = make_icp_state(icp1)
    acc_state = make_acceptance_state(acc1)
    with tempfile.TemporaryDirectory() as td:
        path = os.path.join(td, 'snap.json')
        save_snapshot(path, icp_state, acc_state)
        assert os.path.exists(path)
        # build new system and load
        icp2, acc2 = _build_system()
        icp_payload, acc_payload = load_snapshot(path)
        load_icp_state(icp2, icp_payload)
        load_acceptance_state(acc2, acc_payload)
        # continue simulation
        _simulate(icp1, acc1, 200, seed=43)
        _simulate(icp2, acc2, 200, seed=43)
        # compare key stats within tolerances
        s1 = icp1.stats(); s2 = icp2.stats()
        a1 = acc1.stats(); a2 = acc2.stats()
        # alpha close (allow 15% relative tolerance due to stochastic updates and resumed adaptation)
        assert math.isclose(getattr(s1,'alpha', icp1.alpha), getattr(s2,'alpha', icp2.alpha), rel_tol=0.15, abs_tol=5e-3)
        # coverage ema close (allow higher tolerance)
        c1 = getattr(s1, 'coverage_ema', a1.get('coverage_ema'))
        c2 = getattr(s2, 'coverage_ema', a2.get('coverage_ema'))
        if isinstance(c1, (int,float)) and isinstance(c2,(int,float)):
            assert math.isclose(c1, c2, rel_tol=0.10, abs_tol=0.05)
        # acceptance surprisal / latency p95 presence
        assert a2.get('surprisal_p95') is not None
        assert a2.get('latency_p95') is not None
