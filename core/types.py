"""
Aurora+ScalpBot — core/types.py
--------------------------------
Single-file module: base data structures, enums, invariants, and utility
formulas that encode the R1 implementation contract.

This file is **self-contained** and includes minimal self-tests at the bottom
(`python core/types.py` runs them). Paste it into `aurora/core/types.py`.

Covers R1 sections:
- §3 Нотація (notation)
- §4 Edge-бюджет і очікуваність угоди (edge math)
- §6 Калібрування (interfaces/metrics only)
- §8 Режими (types only)
- §9 TCA/Latency (types + helpers)
- §11 Динамічний Келлі (helpers only)
- §12 EVT-CVaR (types only)
- §15 XAI-логування (XAI record schema)

No external deps beyond stdlib + typing + math + dataclasses + enum.
NumPy is optional (used only if available to pretty-print/convert arrays).
"""
from __future__ import annotations

from collections.abc import Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from enum import Enum, IntEnum
import json
import math
import time
from typing import Any

try:  # NumPy is optional
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - optional path
    np = None  # type: ignore


# =============================
# Enums & constants (execution)
# =============================

class Side(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

class OrderType(str, Enum):
    LIMIT = "LIMIT"
    MARKET = "MARKET"

class TimeInForce(str, Enum):
    GTC = "GTC"      # Good-Till-Cancel
    IOC = "IOC"      # Immediate-Or-Cancel
    FOK = "FOK"      # Fill-Or-Kill

class ExecMode(str, Enum):
    # NOTE: 'shadow' runtime mode removed project-wide (2025-08-30).
    # Historical references may exist in tests or archive; do not use at runtime.
    PAPER = "paper"     # sim-exchange
    LIVE = "live"       # real venue

class MarketRegime(str, Enum):
    TREND = "trend"
    GRIND = "grind"
    CHAOS = "chaos"
    TRANSITION = "transition"

class WhyCode(IntEnum):
    """WHY-codes for XAI decision traces (non-exhaustive).
    Codes grouped by domain: 1xx=pre-trade gates, 2xx=risk, 3xx=calibration,
    4xx=execution/TCA, 5xx=infra.
    """
    OK = 0
    # 1xx pre-trade / entry gates
    P_THRESHOLD_FAIL = 101            # p <= p*(c') + δ
    REGIME_NOT_PERMITTED = 102        # regime gate denies
    TCA_NEGATIVE = 103                # E[Π(ℓ)] ≤ 0 under SLA
    ICP_UNCERTAIN = 104               # conformal uncertainty high
    SLA_LATENCY_BREACH = 105          # latency > budget
    # 2xx risk
    CVAR_PER_TRADE_BREACH = 201
    CVAR_PORTFOLIO_BREACH = 202
    INVENTORY_LIMIT = 203
    DD_LIMIT = 204
    SPREAD_TOO_WIDE = 205
    VOLATILITY_TOO_HIGH = 206
    LIQUIDITY_TOO_LOW = 207
    # 3xx calibration / model quality
    CALIBRATION_DRIFT = 301
    ECE_BAD = 302
    BRIER_BAD = 303
    LOGLOSS_BAD = 304
    # 4xx execution / fills
    QUEUE_RISK = 401
    ADVERSE_SELECTION = 402
    HAZARD_TOO_LOW = 403
    # 5xx infra
    CONFIG_INVALID = 501
    CLOCK_SKEW = 502


# =============================
# Core dataclasses (notation)
# =============================

@dataclass(slots=True)
class Trade:
    timestamp: float
    price: float
    size: float
    side: Side  # aggression side (taker)

    def __post_init__(self) -> None:
        if not (self.price > 0 and self.size >= 0):
            raise ValueError("Trade invalid: price>0 and size>=0 required")


@dataclass(slots=True)
class MarketSnapshot:
    """L2/L3 snapshot in event-time.

    - bid/ask price at best levels
    - Lk aggregated volumes at bid/ask (lengths may be >= k)
    - recent trades within a window (optional)
    """
    timestamp: float
    bid_price: float
    ask_price: float
    bid_volumes_l: Sequence[float]  # e.g., L5
    ask_volumes_l: Sequence[float]
    trades: Sequence[Trade] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not (self.ask_price > self.bid_price > 0):
            raise ValueError("MarketSnapshot: ask must be > bid > 0")
        if any(v < 0 for v in self.bid_volumes_l) or any(v < 0 for v in self.ask_volumes_l):
            raise ValueError("MarketSnapshot: volumes must be non-negative")

    # Convenience metrics
    @property
    def mid(self) -> float:
        return 0.5 * (self.bid_price + self.ask_price)

    @property
    def spread(self) -> float:
        return self.ask_price - self.bid_price

    def spread_bps(self) -> float:
        return 1e4 * self.spread / self.mid

    def l_sum(self, levels: int = 5) -> tuple[float, float]:
        b = sum(self.bid_volumes_l[:levels])
        a = sum(self.ask_volumes_l[:levels])
        return b, a

    def obi(self, levels: int = 5) -> float:
        b, a = self.l_sum(levels)
        denom = b + a
        return 0.0 if denom == 0 else (b - a) / denom

    def microprice(self, levels: int = 1) -> float:
        if levels <= 1:
            b1 = self.bid_volumes_l[0] if self.bid_volumes_l else 0.0
            a1 = self.ask_volumes_l[0] if self.ask_volumes_l else 0.0
            denom = b1 + a1
            return self.mid if denom == 0 else (a1 * self.bid_price + b1 * self.ask_price) / denom
        # weighted microprice over Lk using mid as proxy where not defined
        b, a = self.l_sum(levels)
        denom = b + a
        return self.mid if denom == 0 else (a * self.bid_price + b * self.ask_price) / denom


@dataclass(slots=True)
class ProbabilityMetrics:
    ece: float | None = None
    brier: float | None = None
    logloss: float | None = None

    def lambda_cal(self, *, eta: float = 10.0, zeta: float = 5.0) -> float:
        """Calibration multiplier λ_cal (see Road_map suggestion).
        λ_cal = exp(-eta*ECE) * exp(-zeta*LogLoss). Missing metrics => neutral 1.0.
        """
        ece = 0.0 if self.ece is None else float(self.ece)
        logloss = 0.0 if self.logloss is None else float(self.logloss)
        return math.exp(-eta * ece) * math.exp(-zeta * logloss)


@dataclass(slots=True)
class ConformalInterval:
    lower: float
    upper: float

    def contains(self, p: float) -> bool:
        return self.lower <= p <= self.upper


@dataclass(slots=True)
class Signal:
    timestamp: float
    symbol: str
    score: float
    raw_probability: float
    calibrated_probability: float
    confidence: ConformalInterval | None = None
    features: Mapping[str, float] = field(default_factory=dict)
    metrics: ProbabilityMetrics = field(default_factory=ProbabilityMetrics)

    def __post_init__(self) -> None:
        if not (0.0 <= self.raw_probability <= 1.0):
            raise ValueError("raw_probability must be in [0,1]")
        if not (0.0 <= self.calibrated_probability <= 1.0):
            raise ValueError("calibrated_probability must be in [0,1]")


@dataclass(slots=True)
class EdgeBreakdown:
    raw_edge_bps: float = 0.0
    fees_bps: float = 0.0
    slippage_bps: float = 0.0
    adverse_bps: float = 0.0
    latency_bps: float = 0.0
    rebates_bps: float = 0.0

    def net_edge_bps(self) -> float:
        return (self.raw_edge_bps - self.fees_bps - self.slippage_bps -
                self.adverse_bps - self.latency_bps + self.rebates_bps)


@dataclass(slots=True)
class RiskLimits:
    cvar95_per_trade_bps: float = 0.0
    cvar95_portfolio_bps: float = 0.0
    max_spread_bps: float = 50.0
    max_latency_ms: float = 50.0


@dataclass(slots=True)
class RiskGatesStatus:
    regime_ok: bool = True
    tca_positive: bool = True
    cvar_trade_ok: bool = True
    cvar_portfolio_ok: bool = True
    spread_ok: bool = True
    volatility_ok: bool = True
    latency_ok: bool = True
    liquidity_ok: bool = True

    def all_ok(self) -> bool:
        return all([
            self.regime_ok, self.tca_positive, self.cvar_trade_ok,
            self.cvar_portfolio_ok, self.spread_ok, self.volatility_ok,
            self.latency_ok, self.liquidity_ok,
        ])


@dataclass(slots=True)
class XAIRecord:
    """Full decision trace for one action (entry/exit/adjust)."""
    timestamp: float
    symbol: str
    side: Side | None
    signal: Signal
    edge: EdgeBreakdown
    risk_gates: RiskGatesStatus
    why_codes: list[WhyCode] = field(default_factory=list)
    extras: MutableMapping[str, Any] = field(default_factory=dict)

    # P3-α Governance fields
    sprt_llr: float | None = None          # SPRT log-likelihood ratio
    sprt_conf: float | None = None         # SPRT decision confidence [0,1]
    alpha_spent: float | None = None       # α budget spent on this decision

    def to_json(self) -> str:
        def _conv(o: Any) -> Any:
            if isinstance(o, Enum):
                return o.value
            if hasattr(o, "__dict__"):
                return json.loads(json.dumps(o, default=_conv))
            if np is not None and isinstance(o, (np.ndarray,)):
                return o.tolist()
            return o
        return json.dumps(self, default=_conv, ensure_ascii=False, separators=(",", ":"))


# =============================
# Math utilities (edge, TCA, Kelly)
# =============================

def expected_pnl(p: float, G: float, L: float, c: float) -> float:
    """E[Π] = p·G − (1−p)·L − c (units consistent, e.g., bps).
    Returns expected *net* outcome after TCA components (fees/adv/slip/lat − rebates).
    """
    if not (0.0 <= p <= 1.0):
        raise ValueError("p must be in [0,1]")
    if G < 0 or L < 0:
        raise ValueError("G and L must be non-negative")
    return p * G - (1.0 - p) * L - c


def p_star_threshold(r: float, c_prime: float, delta: float = 0.0) -> float:
    """Minimal calibrated probability to enter, given payoff ratio r=G/L and c' = c/L.
    p* = (1 + c') / (1 + r). A practical buffer δ≥0 can be added: p > p* + δ.
    """
    if r <= 0:
        raise ValueError("r must be > 0")
    if c_prime < 0:
        raise ValueError("c' must be ≥ 0")
    base = (1.0 + c_prime) / (1.0 + r)
    return min(1.0, max(0.0, base + max(0.0, delta)))


def latency_degradation(edge0_bps: float, kappa_bps_per_ms: float, latency_ms: float) -> float:
    """E[Π(ℓ)] ≈ E[Π(0)] − κ·ℓ  ⇒ returns edge after latency penalty in bps."""
    return edge0_bps - kappa_bps_per_ms * max(0.0, latency_ms)


def raw_kelly_fraction(p: float, b: float, f_max: float = 1.0) -> float:
    """f_raw = clip( (b p − (1−p))/b, 0, f_max ), with b = G/L (odds).
    Guarded for numeric issues; returns 0 if b≤0 or p outside [0,1].
    """
    if not (0.0 <= p <= 1.0) or b <= 0.0:
        return 0.0
    f = (b * p - (1.0 - p)) / b
    return max(0.0, min(f_max, f))


# =============================
# Orders & fills
# =============================

@dataclass(slots=True)
class OrderIntent:
    symbol: str
    side: Side
    size: float
    order_type: OrderType
    tif: TimeInForce = TimeInForce.GTC
    price: float | None = None  # required for LIMIT
    client_id: str | None = None

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("OrderIntent: size must be > 0")
        if self.order_type is OrderType.LIMIT and (self.price is None or self.price <= 0):
            raise ValueError("OrderIntent: LIMIT requires positive price")


@dataclass(slots=True)
class FillOutcome:
    filled: bool
    avg_price: float | None
    filled_size: float
    slippage_bps: float
    adverse_bps: float
    total_cost_bps: float
    latency_ms: float


# =============================
# Helpers
# =============================

def now_ts() -> float:
    return time.time()


def ensure_mapping(maybe: Mapping[str, float] | None) -> Mapping[str, float]:
    return {} if maybe is None else maybe


# =============================
# Self-tests (unit-like, minimal)
# =============================

def _test_snapshot_and_obi() -> None:
    snap = MarketSnapshot(
        timestamp=now_ts(),
        bid_price=100.0,
        ask_price=100.1,
        bid_volumes_l=[100, 200, 300, 400, 500],
        ask_volumes_l=[150, 250, 350, 450, 550],
        trades=(
            Trade(timestamp=now_ts(), price=100.05, size=10, side=Side.BUY),
        ),
    )
    assert snap.ask_price > snap.bid_price
    assert abs(snap.mid - 100.05) < 1e-9
    assert 0.0 <= snap.spread_bps() < 10.0
    obi = snap.obi(levels=2)
    assert -1.0 <= obi <= 1.0


def _test_edge_math() -> None:
    # Example: G=8bps, L=6bps, total costs c=2bps → r=8/6=1.333, c'=2/6≈0.333
    p_star = p_star_threshold(r=8/6, c_prime=2/6, delta=0.02)
    # exact p*=(1+0.3333)/(1+1.3333)=1.3333/2.3333=0.5714…, +0.02 => ≈0.5914
    assert 0.58 < p_star < 0.60
    e = expected_pnl(p=0.62, G=8.0, L=6.0, c=2.0)
    # E = 0.62*8 − 0.38*6 − 2 = 4.96 − 2.28 − 2 = 0.68 bps > 0
    assert abs(e - 0.68) < 1e-9 and e > 0


def _test_kelly() -> None:
    f = raw_kelly_fraction(p=0.60, b=2.0, f_max=0.25)
    # (2*0.6 − 0.4)/2 = 0.4 → clipped to 0.25
    assert abs(f - 0.25) < 1e-9


def _test_xai_record() -> None:
    sig = Signal(
        timestamp=now_ts(),
        symbol="SOONUSDT",
        score=1.23,
        raw_probability=0.58,
        calibrated_probability=0.61,
        confidence=ConformalInterval(0.54, 0.66),
        features={"obi": 0.12, "tfi": -0.08},
        metrics=ProbabilityMetrics(ece=0.03, brier=0.16, logloss=0.48),
    )
    xai = XAIRecord(
        timestamp=now_ts(),
        symbol="SOONUSDT",
        side=Side.BUY,
        signal=sig,
        edge=EdgeBreakdown(raw_edge_bps=9, fees_bps=2, slippage_bps=3,
                           adverse_bps=1, latency_bps=1, rebates_bps=0.5),
        risk_gates=RiskGatesStatus(regime_ok=True, tca_positive=True,
                                   cvar_trade_ok=True, cvar_portfolio_ok=True,
                                   spread_ok=True, volatility_ok=True,
                                   latency_ok=True, liquidity_ok=True),
        why_codes=[WhyCode.OK],
        extras={"regime": MarketRegime.TREND.value},
    )
    s = xai.to_json()
    assert isinstance(s, str) and "SOONUSDT" in s and "why_codes" in s


if __name__ == "__main__":  # minimal self-test runner
    _test_snapshot_and_obi()
    _test_edge_math()
    _test_kelly()
    _test_xai_record()
    print("OK - core/types.py self-tests passed")
