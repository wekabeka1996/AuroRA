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

from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple, Union
import json
import math
import time
from decimal import Decimal

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
    price: Decimal
    size: Decimal
    side: Side  # aggression side (taker)

    def __post_init__(self) -> None:
        self.price = Decimal(str(self.price))
        self.size = Decimal(str(self.size))
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
    bid_price: Decimal
    ask_price: Decimal
    bid_volumes_l: Sequence[Decimal]  # e.g., L5
    ask_volumes_l: Sequence[Decimal]
    trades: Sequence[Trade] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        self.bid_price = Decimal(str(self.bid_price))
        self.ask_price = Decimal(str(self.ask_price))
        self.bid_volumes_l = [Decimal(str(v)) for v in self.bid_volumes_l]
        self.ask_volumes_l = [Decimal(str(v)) for v in self.ask_volumes_l]
        if not (self.ask_price > self.bid_price > 0):
            raise ValueError("MarketSnapshot: ask must be > bid > 0")
        if any(v < 0 for v in self.bid_volumes_l) or any(v < 0 for v in self.ask_volumes_l):
            raise ValueError("MarketSnapshot: volumes must be non-negative")

    # Convenience metrics
    @property
    def mid(self) -> Decimal:
        return (self.bid_price + self.ask_price) / Decimal("2")

    @property
    def spread(self) -> Decimal:
        return self.ask_price - self.bid_price

    def spread_bps(self) -> Decimal:
        return Decimal("10000") * self.spread / self.mid

    def l_sum(self, levels: int = 5) -> Tuple[Decimal, Decimal]:
        b = sum(self.bid_volumes_l[:levels], Decimal(0))
        a = sum(self.ask_volumes_l[:levels], Decimal(0))
        return b, a

    def obi(self, levels: int = 5) -> Decimal:
        b, a = self.l_sum(levels)
        denom = b + a
        return Decimal("0") if denom == 0 else (b - a) / denom

    def microprice(self, levels: int = 1) -> Decimal:
        if levels <= 1:
            b1 = self.bid_volumes_l[0] if self.bid_volumes_l else Decimal("0")
            a1 = self.ask_volumes_l[0] if self.ask_volumes_l else Decimal("0")
            denom = b1 + a1
            return self.mid if denom == 0 else (a1 * self.bid_price + b1 * self.ask_price) / denom
        # weighted microprice over Lk using mid as proxy where not defined
        b, a = self.l_sum(levels)
        denom = b + a
        return self.mid if denom == 0 else (a * self.bid_price + b * self.ask_price) / denom


@dataclass(slots=True)
class ProbabilityMetrics:
    ece: Optional[float] = None
    brier: Optional[float] = None
    logloss: Optional[float] = None

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
    confidence: Optional[ConformalInterval] = None
    features: Mapping[str, float] = field(default_factory=dict)
    metrics: ProbabilityMetrics = field(default_factory=ProbabilityMetrics)

    def __post_init__(self) -> None:
        if not (0.0 <= self.raw_probability <= 1.0):
            raise ValueError("raw_probability must be in [0,1]")
        if not (0.0 <= self.calibrated_probability <= 1.0):
            raise ValueError("calibrated_probability must be in [0,1]")


@dataclass(slots=True)
class EdgeBreakdown:
    raw_edge_bps: Decimal = Decimal("0")
    fees_bps: Decimal = Decimal("0")
    slippage_bps: Decimal = Decimal("0")
    adverse_bps: Decimal = Decimal("0")
    latency_bps: Decimal = Decimal("0")
    rebates_bps: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.raw_edge_bps = Decimal(str(self.raw_edge_bps))
        self.fees_bps = Decimal(str(self.fees_bps))
        self.slippage_bps = Decimal(str(self.slippage_bps))
        self.adverse_bps = Decimal(str(self.adverse_bps))
        self.latency_bps = Decimal(str(self.latency_bps))
        self.rebates_bps = Decimal(str(self.rebates_bps))

    def net_edge_bps(self) -> Decimal:
        return (self.raw_edge_bps - self.fees_bps - self.slippage_bps -
                self.adverse_bps - self.latency_bps + self.rebates_bps)


@dataclass(slots=True)
class RiskLimits:
    cvar95_per_trade_bps: Decimal = Decimal("0")
    cvar95_portfolio_bps: Decimal = Decimal("0")
    max_spread_bps: Decimal = Decimal("50")
    max_latency_ms: Decimal = Decimal("50")

    def __post_init__(self) -> None:
        self.cvar95_per_trade_bps = Decimal(str(self.cvar95_per_trade_bps))
        self.cvar95_portfolio_bps = Decimal(str(self.cvar95_portfolio_bps))
        self.max_spread_bps = Decimal(str(self.max_spread_bps))
        self.max_latency_ms = Decimal(str(self.max_latency_ms))


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
    side: Optional[Side]
    signal: Signal
    edge: EdgeBreakdown
    risk_gates: RiskGatesStatus
    why_codes: List[WhyCode] = field(default_factory=list)
    extras: MutableMapping[str, Any] = field(default_factory=dict)
    
    # P3-α Governance fields
    sprt_llr: Optional[float] = None          # SPRT log-likelihood ratio
    sprt_conf: Optional[float] = None         # SPRT decision confidence [0,1]
    alpha_spent: Optional[float] = None       # α budget spent on this decision

    def to_json(self) -> str:
        def _conv(o: Any) -> Any:
            if isinstance(o, Enum):
                return o.value
            if isinstance(o, Decimal):
                return str(o)
            if hasattr(o, "__dict__"):
                return json.loads(json.dumps(o, default=_conv))
            if np is not None and isinstance(o, (np.ndarray,)):
                return o.tolist()
            return o
        return json.dumps(self, default=_conv, ensure_ascii=False, separators=(",", ":"))


# =============================
# Math utilities (edge, TCA, Kelly)
# =============================

def expected_pnl(p: Decimal, G: Decimal, L: Decimal, c: Decimal) -> Decimal:
    """E[Π] = p·G − (1−p)·L − c (units consistent, e.g., bps).
    Returns expected *net* outcome after TCA components (fees/adv/slip/lat − rebates).
    """
    p = Decimal(str(p))
    G = Decimal(str(G))
    L = Decimal(str(L))
    c = Decimal(str(c))
    if not (Decimal("0") <= p <= Decimal("1")):
        raise ValueError("p must be in [0,1]")
    if G < 0 or L < 0:
        raise ValueError("G and L must be non-negative")
    return p * G - (Decimal("1") - p) * L - c


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
    price: Optional[float] = None  # required for LIMIT
    client_id: Optional[str] = None

    def __post_init__(self) -> None:
        if self.size <= 0:
            raise ValueError("OrderIntent: size must be > 0")
        if self.order_type is OrderType.LIMIT and (self.price is None or self.price <= 0):
            raise ValueError("OrderIntent: LIMIT requires positive price")


@dataclass(slots=True)
class FillOutcome:
    filled: bool
    avg_price: Optional[Decimal]
    filled_size: Decimal
    slippage_bps: Decimal
    adverse_bps: Decimal
    total_cost_bps: Decimal
    latency_ms: Decimal

    def __post_init__(self) -> None:
        if self.avg_price is not None:
            self.avg_price = Decimal(str(self.avg_price))
        self.filled_size = Decimal(str(self.filled_size))
        self.slippage_bps = Decimal(str(self.slippage_bps))
        self.adverse_bps = Decimal(str(self.adverse_bps))
        self.total_cost_bps = Decimal(str(self.total_cost_bps))
        self.latency_ms = Decimal(str(self.latency_ms))


# =============================
# Helpers
# =============================

def now_ts() -> float:
    return time.time()


def ensure_mapping(maybe: Optional[Mapping[str, float]]) -> Mapping[str, float]:
    return {} if maybe is None else maybe


# =============================
# Self-tests (unit-like, minimal)
# =============================

def _test_snapshot_and_obi() -> None:
    snap = MarketSnapshot(
        timestamp=now_ts(),
        bid_price=Decimal("100.0"),
        ask_price=Decimal("100.1"),
        bid_volumes_l=[Decimal("100"), Decimal("200"), Decimal("300"), Decimal("400"), Decimal("500")],
        ask_volumes_l=[Decimal("150"), Decimal("250"), Decimal("350"), Decimal("450"), Decimal("550")],
        trades=(
            Trade(timestamp=now_ts(), price=Decimal("100.05"), size=Decimal("10"), side=Side.BUY),
        ),
    )
    assert snap.ask_price > snap.bid_price
    assert abs(snap.mid - Decimal("100.05")) < Decimal("1e-9")
    assert Decimal("0") <= snap.spread_bps() < Decimal("10")
    obi = snap.obi(levels=2)
    assert Decimal("-1") <= obi <= Decimal("1")


def _test_edge_math() -> None:
    # Example: G=8bps, L=6bps, total costs c=2bps → r=8/6=1.333, c'=2/6≈0.333
    p_star = p_star_threshold(r=8/6, c_prime=2/6, delta=0.02)
    # exact p*=(1+0.3333)/(1+1.3333)=1.3333/2.3333=0.5714…, +0.02 => ≈0.5914
    assert 0.58 < p_star < 0.60
    e = expected_pnl(p=Decimal("0.62"), G=Decimal("8.0"), L=Decimal("6.0"), c=Decimal("2.0"))
    # E = 0.62*8 − 0.38*6 − 2 = 4.96 − 2.28 − 2 = 0.68 bps > 0
    assert abs(e - Decimal("0.68")) < Decimal("1e-9") and e > 0


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