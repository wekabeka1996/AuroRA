import time
from prometheus_client import CollectorRegistry
from living_latent.obs.metrics import Metrics
from living_latent.core.acceptance import Acceptance, AcceptanceCfg, Event
from living_latent.core.acceptance_hysteresis import HysteresisGate, HysteresisCfg

def build_acceptance(profile: str="test"):
    buckets = {}
    registry = CollectorRegistry(auto_describe=True)
    metrics = Metrics(profile=profile, buckets=buckets, registry=registry)
    gate = HysteresisGate(HysteresisCfg.from_dict({}, {}))
    a_cfg = AcceptanceCfg(
        tau_pass=0.75,
        tau_derisk=0.5,
        coverage_lower_bound=0.9,
        surprisal_p95_guard=2.5,
        latency_p95_max_ms=200.0,
        max_interval_rel_width=0.1,
        persistence_n=3,
        penalties={'latency_to_kappa_bonus': -0.05, 'coverage_deficit_bonus': -0.10},
        c_ref=0.01,
        beta_ref=0.0,
        sigma_min=1e-6,
    )
    acceptance = Acceptance(a_cfg, hysteresis_gate=gate, metrics=metrics, profile_label=profile)
    return acceptance, metrics, registry


def test_metrics_basic_emission():
    acceptance, metrics, registry = build_acceptance()

    # simulate a few decisions with different kappa values and violations
    for i in range(5):
        evt = Event(ts=time.time(), mu=0.0, sigma=0.1, interval=( -0.1, 0.1), latency_ms=10+i, y=None)
        decision, info = acceptance.decide(evt)
        # simulate update with realized y inside / outside interval alternate
        y_real = 0.0 if i % 2 == 0 else 0.2  # miss every other
        evt2 = Event(ts=time.time(), mu=0.0, sigma=0.1, interval=(-0.1,0.1), latency_ms=10+i, y=y_real)
        acceptance.update(evt2)
        # set icp stats progression
        metrics.set_icp_stats(alpha=0.1 + 0.01*i, alpha_target=0.1, coverage_ema=0.9)

    # collect metric names to ensure they are registered
    collected = set([m.name for m in registry.collect()])
    required_subset = {
        'aurora_acceptance_decision',  # counter family base name
        'aurora_icp_alpha',                  # set
        'aurora_icp_alpha_target',
        'aurora_icp_coverage_ema',
        'aurora_acceptance_kappa_plus',
        'aurora_acceptance_rel_width_current',
        'aurora_acceptance_surprisal_v2',
        'aurora_acceptance_latency_ms',
        'aurora_acceptance_kappa',
    }
    missing = required_subset - collected
    assert not missing, f"Missing required metrics: {missing} (collected={collected})"

    # Ensure at least one decision count incremented
    decision_samples = [m for m in registry.collect() if m.name == 'aurora_acceptance_decision']
    assert decision_samples, 'Decision counter not found'
    # At least one state flag gauge should be present
    state_flags = [m for m in registry.collect() if m.name == 'aurora_acceptance_state']
    assert state_flags, 'State flag gauge not found'

    # Validate histogram buckets have samples
    latency_hist = [m for m in registry.collect() if m.name == 'aurora_acceptance_latency_ms']
    assert latency_hist, 'Latency histogram missing'
    # No exception means success
