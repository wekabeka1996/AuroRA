import numpy as np

from living_latent.core.acceptance_hysteresis import HysteresisCfg, HysteresisGate


def synthetic_kappa_plus(n=1000, center=0.6, noise=0.08, seed=42):
    rng = np.random.default_rng(seed)
    base = center + noise * rng.standard_normal(n)
    # occasional dips
    for k in range(100, n, 250):
        base[k:k+30] -= 0.25
    return np.clip(base, 0, 1)


def naive_decisions(kappa_plus, tau_pass=0.72, tau_derisk=0.48):
    out = []
    for k in kappa_plus:
        if k >= tau_pass:
            out.append('PASS')
        elif k >= tau_derisk:
            out.append('DERISK')
        else:
            out.append('BLOCK')
    return out


def test_hysteresis_reduces_flicker():
    kappa_series = synthetic_kappa_plus()
    cfg = HysteresisCfg(
        tau_pass_up=0.78, tau_pass_down=0.72,
        tau_derisk_up=0.55, tau_derisk_down=0.48,
        surprisal_guard_up=10.0, surprisal_guard_down=9.0,  # large to avoid guards interfering
        coverage_lower_bound_up=0.999, coverage_lower_bound_down=0.0,
        latency_p95_max_up_ms=1e9, latency_p95_max_down_ms=1e9,
        dwell_pass_up=5, dwell_pass_down=2,
        dwell_derisk_up=4, dwell_derisk_down=3,
        dwell_block_up=6, dwell_block_down=8
    )
    gate = HysteresisGate(cfg)

    naive = naive_decisions(kappa_series)
    stabilized = []
    for k in kappa_series:
        # raw derived same way as naive (for comparison)
        raw = 'PASS' if k >= cfg.tau_pass_down else ('DERISK' if k >= cfg.tau_derisk_down else 'BLOCK')
        final = gate.apply(raw, kappa_plus=k, p95_surprisal=None, coverage_ema=None, latency_p95=None, rel_width=None)
        stabilized.append(final)

    def count_flips(seq):
        return sum(1 for i in range(1, len(seq)) if seq[i] != seq[i-1])

    flips_naive = count_flips(naive)
    flips_stab = count_flips(stabilized)

    # Expect significant reduction
    assert flips_stab * 2 <= flips_naive, f"Hysteresis insufficient: naive={flips_naive} stabilized={flips_stab}"


def test_block_recovery_requires_dwell():
    # Force drop then recovery
    cfg = HysteresisCfg(
        tau_pass_up=0.78, tau_pass_down=0.72,
        tau_derisk_up=0.55, tau_derisk_down=0.48,
        surprisal_guard_up=10.0, surprisal_guard_down=9.0,
        coverage_lower_bound_up=0.999, coverage_lower_bound_down=0.0,
        latency_p95_max_up_ms=1e9, latency_p95_max_down_ms=1e9,
        dwell_pass_up=3, dwell_pass_down=1,
        dwell_derisk_up=2, dwell_derisk_down=2,
        dwell_block_up=2, dwell_block_down=3
    )
    gate = HysteresisGate(cfg)
    seq = []
    # Start stable PASS
    for _ in range(10):
        seq.append(gate.apply('PASS', 0.85, None, None, None, None))
    # Drop kappa to push BLOCK
    for _ in range(5):
        seq.append(gate.apply('BLOCK', 0.2, None, None, None, None))
    assert gate.current == 'BLOCK'
    # Recover kappa moderately (DERISK band) then PASS
    steps = 0
    while gate.current != 'PASS' and steps < 50:
        seq.append(gate.apply('PASS', 0.82, None, None, None, None))
        steps += 1
    assert gate.current == 'PASS'
    # Ensure took at least combined dwell for block_down + pass_up
    assert steps >= (cfg.dwell_block_down + cfg.dwell_pass_up)
