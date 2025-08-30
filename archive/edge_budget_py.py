"""
Aurora+ScalpBot — repo/core/tca/edge_budget.py
----------------------------------------------
Edge budget math and TCA gate.

Paste into: repo/core/tca/edge_budget.py
Run self-tests: `python repo/core/tca/edge_budget.py`

Implements (per project structure):
- Expected net P&L in bps: E[Π] = p·G − (1−p)·L − c
- Probability threshold p*: for r=G/L and c' = c/L → p* = (1 + c')/(1 + r) + δ
- Latency penalty: edge(ℓ) ≈ edge(0) − κ·ℓ (κ in bps/ms, ℓ in ms)
- Edge breakdown (raw, fees, slippage, adverse, latency, rebates) → net edge
- TCA gate helper: positive expected P&L given p, G, L and breakdown

No external deps; NumPy optional. Provides fallbacks if core types are missing.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional
import math

try:  # optional
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Optional import from aurora.core.types; fallback if not present -------
try:  # pragma: no cover - used during integration
    from aurora.core.types import EdgeBreakdown as _EdgeBreakdown
except Exception:
    _EdgeBreakdown = None  # type: ignore


@dataclass
class EdgeBreakdown:
    """Edge components in **basis points** (bps).

    Positive entries **add** to profitability except costs which are entered
    as positive numbers and subtracted internally in `net_edge_bps()`.
    """
    raw_edge_bps: float = 0.0      # model-estimated gross edge before TCA
    fees_bps: float = 0.0          # taker/maker fees (positive = cost)
    slippage_bps: float = 0.0      # market impact / queue loss
    adverse_bps: float = 0.0       # adverse selection cost
    latency_bps: float = 0.0       # κ·ℓ penalty
    rebates_bps: float = 0.0       # maker rebates (positive = benefit)

    def net_edge_bps(self) -> float:
        return (self.raw_edge_bps - self.fees_bps - self.slippage_bps -
                self.adverse_bps - self.latency_bps + self.rebates_bps)


# If a core EdgeBreakdown exists, we can alias to ensure consistency
if _EdgeBreakdown is not None:  # pragma: no cover
    # lightweight adapter for type-compat; prefer project-local class otherwise
    pass


# =============================
# Core math
# =============================

def expected_pnl_bps(p: float, G_bps: float, L_bps: float, cost_bps: float) -> float:
    """E[Π] in **bps**.
    E[Π] = p·G − (1−p)·L − c
    Requires p∈[0,1], G_bps≥0, L_bps≥0, cost_bps≥0.
    """
    if not (0.0 <= p <= 1.0):
        raise ValueError("p must be in [0,1]")
    if G_bps < 0 or L_bps < 0 or cost_bps < 0:
        raise ValueError("G,L,c must be non-negative")
    return float(p) * float(G_bps) - (1.0 - float(p)) * float(L_bps) - float(cost_bps)


def p_star_threshold(r: float, c_prime: float, delta: float = 0.0) -> float:
    """Minimal calibrated probability p* to enter (optionally with buffer δ≥0).

    r = G/L (payoff odds), c' = c/L (cost normalized by loss). Formula:
    p* = (1 + c') / (1 + r) + δ   (then clipped to [0,1]).
    """
    if r <= 0:
        raise ValueError("r must be > 0")
    if c_prime < 0:
        raise ValueError("c' must be ≥ 0")
    base = (1.0 + float(c_prime)) / (1.0 + float(r))
    return min(1.0, max(0.0, base + max(0.0, float(delta))))


def latency_penalty_bps(kappa_bps_per_ms: float, latency_ms: float) -> float:
    """κ·ℓ with κ in bps/ms and ℓ in ms (non-negative)."""
    return max(0.0, float(kappa_bps_per_ms)) * max(0.0, float(latency_ms))


def apply_latency(edge0_bps: float, kappa_bps_per_ms: float, latency_ms: float) -> float:
    """edge(ℓ) ≈ edge(0) − κ·ℓ (lower bounded by −∞, caller may clip)."""
    return float(edge0_bps) - latency_penalty_bps(kappa_bps_per_ms, latency_ms)


# =============================
# Builders & reports
# =============================

def make_breakdown(
    *,
    raw_edge_bps: float,
    fees_bps: float = 0.0,
    slippage_bps: float = 0.0,
    adverse_bps: float = 0.0,
    rebates_bps: float = 0.0,
    latency_ms: Optional[float] = None,
    kappa_bps_per_ms: float = 0.0,
) -> EdgeBreakdown:
    lat_bps = 0.0 if latency_ms is None else latency_penalty_bps(kappa_bps_per_ms, latency_ms)
    return EdgeBreakdown(
        raw_edge_bps=float(raw_edge_bps),
        fees_bps=float(fees_bps),
        slippage_bps=float(slippage_bps),
        adverse_bps=float(adverse_bps),
        latency_bps=float(lat_bps),
        rebates_bps=float(rebates_bps),
    )


def tca_report(
    *,
    p: float,
    G_bps: float,
    L_bps: float,
    breakdown: EdgeBreakdown,
    delta: float = 0.0,
) -> Dict[str, float]:
    """Return a compact TCA gate report.

    - p: calibrated entry probability
    - G_bps: expected gain if win (bps)
    - L_bps: expected loss if lose (bps)
    - breakdown: EdgeBreakdown costs & rebates
    - δ: additional safety buffer in probability space

    Computes: r, c, c', p*, net_edge_bps, E[Π], and a boolean `tca_ok` (1.0/0.0).
    """
    p = float(p)
    G = max(0.0, float(G_bps))
    L = max(0.0, float(L_bps))
    r = float('inf') if L == 0 else G / L
    c = max(0.0, breakdown.fees_bps + breakdown.slippage_bps + breakdown.adverse_bps + breakdown.latency_bps - breakdown.rebates_bps)
    cp = 0.0 if L == 0 else c / L
    p_star = 0.0 if not math.isfinite(r) else p_star_threshold(r, cp, delta)
    e = expected_pnl_bps(p, G, L, c)
    net_edge = breakdown.net_edge_bps()
    return {
        "p": p,
        "G_bps": G,
        "L_bps": L,
        "r_G_over_L": r if math.isfinite(r) else 0.0,
        "cost_bps": c,
        "c_prime": cp,
        "p_star": p_star,
        "expected_pnl_bps": e,
        "net_edge_bps": net_edge,
        "tca_ok": 1.0 if e > 0.0 and p > p_star else 0.0,
    }


# =============================
# Self-tests
# =============================

def _test_threshold_and_expected_pnl() -> None:
    # Example: G=8, L=6, costs c=2, δ=0.02
    p_star = p_star_threshold(r=8/6, c_prime=2/6, delta=0.02)
    # exact p*≈0.5914
    assert 0.58 < p_star < 0.60
    e = expected_pnl_bps(p=0.62, G_bps=8.0, L_bps=6.0, cost_bps=2.0)
    # E = 0.62*8 − 0.38*6 − 2 = 4.96 − 2.28 − 2 = 0.68 bps
    assert abs(e - 0.68) < 1e-9 and e > 0


def _test_latency_breakdown_and_gate() -> None:
    # κ=0.02 bps/ms, ℓ=10ms → latency=0.2bps
    bd = make_breakdown(raw_edge_bps=9.0, fees_bps=2.0, slippage_bps=3.0, adverse_bps=1.0,
                        rebates_bps=0.5, latency_ms=10.0, kappa_bps_per_ms=0.02)
    net = bd.net_edge_bps()
    # net = 9 - 2 - 3 - 1 - 0.2 + 0.5 = 3.3 bps
    assert abs(net - 3.3) < 1e-9
    rep = tca_report(p=0.62, G_bps=8.0, L_bps=6.0, breakdown=bd, delta=0.02)
    assert rep["tca_ok"] == 1.0 and rep["expected_pnl_bps"] > 0


def _test_apply_latency() -> None:
    out = apply_latency(edge0_bps=5.0, kappa_bps_per_ms=0.05, latency_ms=20.0)
    assert abs(out - 4.0) < 1e-12


if __name__ == "__main__":
    _test_threshold_and_expected_pnl()
    _test_latency_breakdown_and_gate()
    _test_apply_latency()
    print("OK - repo/core/tca/edge_budget.py self-tests passed")
