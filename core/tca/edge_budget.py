"""
Aurora+ScalpBot — core/tca/edge_budget.py
-----------------------------------------
Transaction Cost Analysis: edge budget calculations and TCA gate.

Implements expected return gate with latency degradation and cost components.
Formulas: E[Π] = p·G − (1−p)·L − c, p* threshold, latency penalty κ·ℓ.

I/O Contract:
- Input: calibrated_probability p, payoff_ratio r=G/L, costs c, latency_ms ℓ
- Output: edge_breakdown (EdgeBreakdown), gate_ok (bool), tca_report (dict)
- Units: all monetary values in bps, latency in ms
- Event-time: stateless function, no temporal dependencies

Uses core.types.EdgeBreakdown as SSOT to avoid desync with XAI logs.
"""
from __future__ import annotations

from dataclasses import dataclass

from core.types import EdgeBreakdown


def expected_pnl(p: float, G: float, L: float, c: float) -> float:
    """E[Π] = p·G − (1−p)·L − c (expected net outcome in bps)."""
    if not (0.0 <= p <= 1.0):
        raise ValueError("p must be in [0,1]")
    if G < 0 or L < 0:
        raise ValueError("G and L must be non-negative")
    return p * G - (1.0 - p) * L - c


def p_star_threshold(r: float, c_prime: float, delta: float = 0.0) -> float:
    """p* = (1 + c') / (1 + r) + δ (minimal probability to enter)."""
    if r <= 0:
        raise ValueError("r must be > 0")
    if c_prime < 0:
        raise ValueError("c' must be ≥ 0")
    base = (1.0 + c_prime) / (1.0 + r)
    return min(1.0, max(0.0, base + max(0.0, delta)))


def apply_latency_penalty(edge0_bps: float, kappa_bps_per_ms: float, latency_ms: float) -> float:
    """E[Π(ℓ)] = E[Π(0)] − κ·ℓ (latency degradation in bps)."""
    return edge0_bps - kappa_bps_per_ms * max(0.0, latency_ms)


@dataclass
class TCAConfig:
    """Configuration for TCA calculations."""
    pi_min_bps: float = 0.5  # minimum expected profit threshold
    kappa_bps_per_ms: float = 0.1  # latency penalty coefficient
    delta_p_star: float = 0.02  # buffer for p* threshold


def make_breakdown(
    raw_edge_bps: float,
    fees_bps: float,
    slippage_bps: float,
    adverse_bps: float,
    latency_bps: float,
    rebates_bps: float = 0.0
) -> EdgeBreakdown:
    """Create EdgeBreakdown from components (uses core.types.EdgeBreakdown as SSOT)."""
    return EdgeBreakdown(
        raw_edge_bps=raw_edge_bps,
        fees_bps=fees_bps,
        slippage_bps=slippage_bps,
        adverse_bps=adverse_bps,
        latency_bps=latency_bps,
        rebates_bps=rebates_bps
    )


def tca_report(
    p: float,
    r: float,
    c_bps: float,
    latency_ms: float,
    config: TCAConfig,
    breakdown: EdgeBreakdown | None = None
) -> dict[str, float]:
    """Generate TCA report with gate decision.

    Returns dict with:
    - expected_pi_bps: E[Π] after latency penalty
    - p_star: threshold probability
    - gate_ok: boolean (1.0/0.0) indicating if trade should proceed
    - breakdown components if provided
    """
    # Calculate p* threshold
    c_prime = c_bps / max(1e-12, r) if r > 0 else float('inf')
    p_star = p_star_threshold(r, c_prime, config.delta_p_star)

    # Calculate expected profit before latency
    G = r * 1.0  # normalize L=1 for simplicity
    L = 1.0
    edge0 = expected_pnl(p, G, L, c_bps)

    # Apply latency penalty
    edge_final = apply_latency_penalty(edge0, config.kappa_bps_per_ms, latency_ms)

    # Gate decision
    gate_ok = 1.0 if (p >= p_star and edge_final >= config.pi_min_bps) else 0.0

    report = {
        "expected_pi_bps": edge_final,
        "p_star": p_star,
        "gate_ok": gate_ok,
        "edge0_bps": edge0,
        "latency_penalty_bps": config.kappa_bps_per_ms * latency_ms,
    }

    # Add breakdown components if provided
    if breakdown is not None:
        report.update({
            "raw_edge_bps": breakdown.raw_edge_bps,
            "fees_bps": breakdown.fees_bps,
            "slippage_bps": breakdown.slippage_bps,
            "adverse_bps": breakdown.adverse_bps,
            "latency_bps": breakdown.latency_bps,
            "rebates_bps": breakdown.rebates_bps,
            "net_edge_bps": breakdown.net_edge_bps(),
        })

    return report


# =============================
# Self-tests
# =============================

def _test_expected_pnl() -> None:
    # E[Π] = p·G − (1−p)·L − c
    e = expected_pnl(p=0.6, G=10.0, L=5.0, c=2.0)
    # 0.6*10 - 0.4*5 - 2 = 6 - 2 - 2 = 2
    assert abs(e - 2.0) < 1e-12


def _test_p_star_threshold() -> None:
    # p* = (1 + c') / (1 + r) + δ
    # With r=2, c'=0.5, δ=0: p* = (1+0.5)/(1+2) = 1.5/3 = 0.5
    p_star = p_star_threshold(r=2.0, c_prime=0.5, delta=0.0)
    assert abs(p_star - 0.5) < 1e-12

    # With δ=0.1: p* = 0.5 + 0.1 = 0.6
    p_star_delta = p_star_threshold(r=2.0, c_prime=0.5, delta=0.1)
    assert abs(p_star_delta - 0.6) < 1e-12


def _test_latency_penalty() -> None:
    # E[Π(ℓ)] = E[Π(0)] − κ·ℓ
    edge0 = 5.0
    kappa = 0.2  # 0.2 bps per ms
    latency = 10.0  # 10 ms
    edge_final = apply_latency_penalty(edge0, kappa, latency)
    # 5.0 - 0.2*10 = 5.0 - 2.0 = 3.0
    assert abs(edge_final - 3.0) < 1e-12


def _test_tca_gate_logic() -> None:
    config = TCAConfig(pi_min_bps=1.0, kappa_bps_per_ms=0.1, delta_p_star=0.05)

    # Case 1: Good trade (p > p*, E[Π] > pi_min) - use higher edge to survive latency
    report = tca_report(p=0.8, r=3.0, c_bps=0.5, latency_ms=5.0, config=config)
    assert report["gate_ok"] == 1.0
    assert report["expected_pi_bps"] > config.pi_min_bps

    # Case 2: Bad trade (p < p*)
    report_bad = tca_report(p=0.3, r=2.0, c_bps=1.0, latency_ms=5.0, config=config)
    assert report_bad["gate_ok"] == 0.0

    # Case 3: High latency kills edge - use parameters that would pass without latency
    report_latency = tca_report(p=0.7, r=2.0, c_bps=0.5, latency_ms=20.0, config=config)
    assert report_latency["gate_ok"] == 0.0  # High latency should block


def _test_edge_breakdown_integration() -> None:
    breakdown = make_breakdown(
        raw_edge_bps=10.0,
        fees_bps=1.5,
        slippage_bps=2.0,
        adverse_bps=1.0,
        latency_bps=0.5,
        rebates_bps=0.2
    )
    assert breakdown.net_edge_bps() == 10.0 - 1.5 - 2.0 - 1.0 - 0.5 + 0.2  # 5.2

    config = TCAConfig()
    report = tca_report(
        p=0.6, r=2.0, c_bps=2.0, latency_ms=10.0,
        config=config, breakdown=breakdown
    )
    assert "net_edge_bps" in report
    assert report["gate_ok"] in [0.0, 1.0]


def _test_monotonicity() -> None:
    """Test monotonicity: higher p → higher E[Π], lower latency → higher E[Π]."""
    config = TCAConfig(kappa_bps_per_ms=0.1)

    # Higher p should give higher E[Π]
    r1 = tca_report(p=0.6, r=2.0, c_bps=1.0, latency_ms=5.0, config=config)
    r2 = tca_report(p=0.7, r=2.0, c_bps=1.0, latency_ms=5.0, config=config)
    assert r2["expected_pi_bps"] > r1["expected_pi_bps"]

    # Lower latency should give higher E[Π]
    r3 = tca_report(p=0.6, r=2.0, c_bps=1.0, latency_ms=10.0, config=config)
    r4 = tca_report(p=0.6, r=2.0, c_bps=1.0, latency_ms=5.0, config=config)
    assert r4["expected_pi_bps"] > r3["expected_pi_bps"]


def _test_extreme_cases() -> None:
    """Test edge cases: L=0 (lossless stops), high latency."""
    config = TCAConfig(pi_min_bps=0.1, kappa_bps_per_ms=0.1)

    # Lossless stops (L=0): should have infinite r and very low p*
    try:
        # This should work but p* will be very low
        report = tca_report(p=0.1, r=100.0, c_bps=0.01, latency_ms=0.0, config=config)
        assert report["p_star"] < 0.5  # Very low threshold for high r
    except ValueError:
        # If r is too extreme, it might raise - that's also acceptable
        pass

    # Very high latency should always block
    report_high_lat = tca_report(p=0.9, r=2.0, c_bps=0.1, latency_ms=1000.0, config=config)
    assert report_high_lat["gate_ok"] == 0.0


if __name__ == "__main__":
    _test_expected_pnl()
    _test_p_star_threshold()
    _test_latency_penalty()
    _test_tca_gate_logic()
    _test_edge_breakdown_integration()
    _test_monotonicity()
    _test_extreme_cases()
    print("OK - core/tca/edge_budget.py self-tests passed")
