"""
Aurora+ScalpBot — repo/core/sizing/lambdas.py
---------------------------------------------
Lambda multipliers for Kelly orchestration: calibration, regime, liquidity,
drawdown, and latency. Pure policy + smooth scalers with sensible defaults.

Paste into: repo/core/sizing/lambdas.py
Run self-tests: `python repo/core/sizing/lambdas.py`

Implements (per project structure):
- λ_cal from ProbabilityMetrics (ECE, LogLoss) via smooth exponential penalties
- λ_reg from regime/tradeability flags (trend, grind allowed by default)
- λ_liq from microstructure liquidity (spread_bps, TTD seconds at best)
- λ_dd from account/strategy drawdown ratio vs limit
- λ_lat from latency vs SLA (ms)
- `combine_lambdas` helper and `LambdaPolicy` convenience wrapper

No external deps; NumPy optional. Standalone (fallback ProbabilityMetrics provided).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Mapping, Optional
import math

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Optional import from project calibrator; fallback if not present ------
try:  # pragma: no cover - used during integration
    from aurora.core.calibration import ProbabilityMetrics  # type: ignore
except Exception:
    @dataclass
    class ProbabilityMetrics:  # minimal fallback
        ece: Optional[float] = None
        brier: Optional[float] = None
        logloss: Optional[float] = None


# =============================
# Core λ functions (each returns a value in [0,1])
# =============================

@dataclass
class LambdaCalConfig:
    ece_target: float = 0.02   # acceptable ECE
    ll_target: float = 0.70    # acceptable LogLoss (binary)
    eta: float = 12.0          # penalty weight for ECE above target
    zeta: float = 6.0          # penalty weight for LogLoss above target


def lambda_cal(metrics: ProbabilityMetrics, cfg: LambdaCalConfig = LambdaCalConfig()) -> float:
    """Calibration multiplier from ECE & LogLoss (higher → worse → smaller λ).

    λ_cal = exp(-η·max(0, ECE−ECE₀)) · exp(-ζ·max(0, LL−LL₀))
    
    If metrics are missing, returns 1.0 (no penalty).
    """
    ece = float(metrics.ece) if metrics and metrics.ece is not None else None
    ll = float(metrics.logloss) if metrics and metrics.logloss is not None else None
    if ece is None and ll is None:
        return 1.0
    pen_e = max(0.0, (ece - cfg.ece_target)) if ece is not None else 0.0
    pen_l = max(0.0, (ll - cfg.ll_target)) if ll is not None else 0.0
    lam = math.exp(-cfg.eta * pen_e) * math.exp(-cfg.zeta * pen_l)
    return max(0.0, min(1.0, lam))


@dataclass
class LambdaRegConfig:
    allowed: tuple = ("trend", "grind")  # tradeable regimes
    off_regime_penalty: float = 0.2       # λ when regime not allowed but tradeable


def lambda_reg(*, tradeable: bool, regime: Optional[str], cfg: LambdaRegConfig = LambdaRegConfig()) -> float:
    """Regime multiplier.

    - If not tradeable: 0.
    - If regime ∈ allowed: 1.
    - Else: off_regime_penalty (e.g., 0.2).
    """
    if not tradeable:
        return 0.0
    if regime is None:
        return 1.0
    return 1.0 if regime in cfg.allowed else max(0.0, min(1.0, cfg.off_regime_penalty))


@dataclass
class LambdaLiqConfig:
    spread_ref_bps: float = 2.0   # above this, penalize
    ttd_ref_s: float = 0.5        # below this, penalize (queue likely to deplete fast)
    a_spread: float = 0.25        # penalty slope for spread excess
    b_ttd: float = 1.50           # penalty slope for TTD shortfall (relative to ref)


def lambda_liq(*, spread_bps: Optional[float], ttd_s: Optional[float], cfg: LambdaLiqConfig = LambdaLiqConfig()) -> float:
    """Liquidity multiplier from spread & time-to-depletion (best-quote).

    λ_liq = exp(-a·max(0, spread−s₀)) · exp(-b·max(0, (t₀−TTD)/t₀))
    """
    s = None if spread_bps is None else max(0.0, float(spread_bps))
    ttd = None if ttd_s is None else max(0.0, float(ttd_s))
    pen_s = 0.0 if s is None else max(0.0, s - cfg.spread_ref_bps)
    pen_t = 0.0 if ttd is None else max(0.0, (cfg.ttd_ref_s - ttd) / max(1e-9, cfg.ttd_ref_s))
    lam = math.exp(-cfg.a_spread * pen_s) * math.exp(-cfg.b_ttd * pen_t)
    return max(0.0, min(1.0, lam))


@dataclass
class LambdaDDConfig:
    gamma: float = 1.5  # curvature for drawdown penalty


def lambda_dd(*, dd_ratio: float, cfg: LambdaDDConfig = LambdaDDConfig()) -> float:
    """Drawdown multiplier, dd_ratio = current_DD / DD_limit.

    λ_dd = max(0, 1 − dd_ratio)^γ.
    """
    x = max(0.0, float(dd_ratio))
    base = max(0.0, 1.0 - x)
    return max(0.0, min(1.0, base ** cfg.gamma))


@dataclass
class LambdaLatConfig:
    alpha: float = 3.0  # slope for SLA overrun in relative terms


def lambda_lat(*, latency_ms: float, sla_ms: float, cfg: LambdaLatConfig = LambdaLatConfig()) -> float:
    """Latency multiplier from SLA (lower is better).

    over = max(0, (ℓ−SLA)/SLA). λ_lat = exp(−α·over).
    """
    SLA = max(1e-9, float(sla_ms))
    over = max(0.0, float(latency_ms) - SLA) / SLA
    return max(0.0, min(1.0, math.exp(-cfg.alpha * over)))


# =============================
# Combiners & Policy wrapper
# =============================

def combine_lambdas(d: Mapping[str, float]) -> float:
    prod = 1.0
    for k, v in d.items():
        try:
            x = float(v)
        except Exception:
            x = 1.0
        if x < 0.0:
            x = 0.0
        if x > 1.0:
            x = 1.0
        prod *= x
    return max(0.0, min(1.0, prod))


@dataclass
class LambdaPolicy:
    cal: LambdaCalConfig = LambdaCalConfig()
    reg: LambdaRegConfig = LambdaRegConfig()
    liq: LambdaLiqConfig = LambdaLiqConfig()
    dd: LambdaDDConfig = LambdaDDConfig()
    lat: LambdaLatConfig = LambdaLatConfig()

    def compute(self,
                *,
                metrics: Optional[ProbabilityMetrics],
                tradeable: bool,
                regime: Optional[str],
                spread_bps: Optional[float],
                ttd_s: Optional[float],
                dd_ratio: float,
                latency_ms: float,
                sla_ms: float) -> Dict[str, float]:
        l_cal = lambda_cal(metrics, self.cal)
        l_reg = lambda_reg(tradeable=tradeable, regime=regime, cfg=self.reg)
        l_liq = lambda_liq(spread_bps=spread_bps, ttd_s=ttd_s, cfg=self.liq)
        l_dd = lambda_dd(dd_ratio=dd_ratio, cfg=self.dd)
        l_lat = lambda_lat(latency_ms=latency_ms, sla_ms=sla_ms, cfg=self.lat)
        d = {"cal": l_cal, "reg": l_reg, "liq": l_liq, "dd": l_dd, "lat": l_lat}
        d["lambda_product"] = combine_lambdas(d)
        return d


# =============================
# Self-tests
# =============================

def _test_lambda_cal_monotone() -> None:
    m_good = ProbabilityMetrics(ece=0.01, logloss=0.5)
    m_bad = ProbabilityMetrics(ece=0.08, logloss=1.0)
    lc = lambda_cal(m_good)
    lb = lambda_cal(m_bad)
    assert 0.0 <= lb <= lc <= 1.0


def _test_lambda_reg() -> None:
    assert lambda_reg(tradeable=False, regime="trend") == 0.0
    assert lambda_reg(tradeable=True, regime="trend") == 1.0
    assert 0.0 <= lambda_reg(tradeable=True, regime="chaos") <= 1.0


def _test_lambda_liq_monotone() -> None:
    # worse spread and smaller TTD → smaller λ
    l1 = lambda_liq(spread_bps=1.5, ttd_s=1.0)
    l2 = lambda_liq(spread_bps=5.0, ttd_s=0.2)
    assert 0.0 <= l2 <= l1 <= 1.0


def _test_lambda_dd_monotone() -> None:
    l0 = lambda_dd(dd_ratio=0.0)
    l5 = lambda_dd(dd_ratio=0.5)
    l9 = lambda_dd(dd_ratio=0.9)
    assert 1.0 >= l0 >= l5 >= l9 >= 0.0


def _test_lambda_lat_monotone() -> None:
    l_ok = lambda_lat(latency_ms=8.0, sla_ms=10.0)
    l_bad = lambda_lat(latency_ms=25.0, sla_ms=10.0)
    assert 0.0 <= l_bad <= l_ok <= 1.0


def _test_policy_product() -> None:
    pol = LambdaPolicy()
    d = pol.compute(metrics=ProbabilityMetrics(ece=0.03, logloss=0.8),
                    tradeable=True, regime="trend",
                    spread_bps=2.5, ttd_s=0.4,
                    dd_ratio=0.3,
                    latency_ms=12.0, sla_ms=10.0)
    assert 0.0 <= d["lambda_product"] <= 1.0 and all(0.0 <= v <= 1.0 for k, v in d.items() if k != "lambda_product")


if __name__ == "__main__":
    _test_lambda_cal_monotone()
    _test_lambda_reg()
    _test_lambda_liq_monotone()
    _test_lambda_dd_monotone()
    _test_lambda_lat_monotone()
    _test_policy_product()
    print("OK - repo/core/sizing/lambdas.py self-tests passed")
