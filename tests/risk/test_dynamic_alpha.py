import math
import pytest

from living_latent.core.icp_dynamic import AdaptiveICP

# Helper factory with small decay / cooldown so tests run fast

def _mk_icp():
    return AdaptiveICP(
        alpha_target=0.10,
        eta=0.01,
        window=256,
        quantile_mode='p2',
        alpha_min=0.06,
        alpha_max=0.20,
        aci_beta=0.2,
        aci_up_thresh=1.25,
        alpha_k_up=0.5,
        cooldown_steps=15,
        decay_tau=40,
    )

# Internal tick: drive only ACI-based modulation (bypasses full update path for determinism)
# Uses private _modulate_alpha (acceptable for white-box dynamics test). If a public
# method is added later (e.g. step(..., aci_value=)), replace here.

def _tick(icp: AdaptiveICP, aci_value: float) -> float:
    icp._modulate_alpha(aci_value=float(aci_value))  # noqa: SLF001 (intentional white-box)
    return icp.effective_alpha()


def test_alpha_spike_up_respects_max():
    icp = _mk_icp()
    # Stable low ACI first -> alpha near base
    last_a = icp.effective_alpha()
    for _ in range(30):
        last_a = _tick(icp, aci_value=1.0)
    assert 0.099 <= last_a <= 0.101

    # Instability spike (ACI well above threshold)
    peak_vals = [1.6] * 20
    seen = []
    for v in peak_vals:
        seen.append(_tick(icp, aci_value=v))

    # Alpha rises but stays within max
    assert max(seen) >= 0.11
    assert max(seen) <= icp.alpha_max + 1e-12


def test_alpha_bounds_clamped_under_extremes():
    icp = _mk_icp()
    # Extremely low ACI values -> alpha not below min
    for _ in range(25):
        a = _tick(icp, aci_value=0.0)
        assert icp.alpha_min - 1e-12 <= a <= icp.alpha_max + 1e-12

    # Extremely high ACI values -> alpha not above max
    for _ in range(25):
        a = _tick(icp, aci_value=3.0)
        assert icp.alpha_min - 1e-12 <= a <= icp.alpha_max + 1e-12


def test_alpha_decays_back_to_base_after_cooldown():
    icp = _mk_icp()
    base = icp.alpha_base

    # Warm-up at base
    for _ in range(20):
        _tick(icp, 1.0)

    # Raise alpha via spike
    for _ in range(20):
        _tick(icp, 1.6)
    a_peak = icp.effective_alpha()
    assert a_peak > base

    # Return to normal ACI, wait cooldown + ~3 * decay_tau
    steps = icp.cooldown_steps + 3 * icp.decay_tau
    a_now = a_peak
    for _ in range(steps):
        a_now = _tick(icp, 1.0)

    # Alpha decayed close to base (<=10% relative deviation)
    assert math.isclose(a_now, base, rel_tol=0.10)
    assert icp.alpha_min - 1e-12 <= a_now <= icp.alpha_max + 1e-12
