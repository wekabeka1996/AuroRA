"""
Aurora+ScalpBot — repo/core/features/absorption.py
--------------------------------------------------
Best-quote absorption metrics from L2 snapshots and recent trades.

Paste into: repo/core/features/absorption.py
Run self-tests: `python repo/core/features/absorption.py`

Implements (per project structure):
- Decomposition at best bid/ask when price unchanged: removal = trades_hit + cancels
- EMAs (half-life) of SELL-MO (hits bid), BUY-MO (hits ask), cancel & replenish
- Absorption fraction, resilience, and pressure scores per side
- TTD (time-to-depletion) proxy at best: q / max(removal_rate − replenish_rate, ε)
- Queue-ahead estimator (simple): current best size (optionally + expected replenishment)

I/O Contract:
- Input: MarketSnapshot with L2 data and recent trades, event-time ordered
- Output: Dict of absorption metrics with specified units
- Units: rate_* fields in volume/second, ttd_* fields in seconds, pressure_* dimensionless
- Event-time: processes snapshots chronologically, no look-ahead bias
- Invariants: absorption_frac in [0,1], ttd >= 0, rates >= 0

Stateless helpers + streaming `AbsorptionStream`.
No external deps; NumPy optional. Uses `core.types` as SSOT.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import math
import time

try:  # optional only
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Imports from core.types (SSOT) -----
from core.types import Trade, Side, MarketSnapshot

# ------------------------------------------------------------------------------

@dataclass
class _EMA:
    half_life_s: float
    value: float = 0.0
    _last_ts: Optional[float] = None

    def update(self, x: float, ts: float) -> float:
        if self._last_ts is None:
            self.value = float(x)
            self._last_ts = float(ts)
            return self.value
        dt = max(0.0, float(ts) - float(self._last_ts))
        lam = math.log(2.0) / max(1e-9, float(self.half_life_s))
        w = math.exp(-lam * dt)
        self.value = w * self.value + (1.0 - w) * float(x)
        self._last_ts = float(ts)
        return self.value


@dataclass
class _State:
    last_ts: Optional[float] = None
    bid_p: Optional[float] = None
    ask_p: Optional[float] = None
    bid_q1: float = 0.0
    ask_q1: float = 0.0


def _sum_trades(trades: Sequence[Trade], side: Side, ts_from: float) -> float:
    s = 0.0
    for tr in trades:
        if float(tr.timestamp) <= ts_from:
            continue
        if str(tr.side) == str(side) or str(tr.side) == side.value:
            s += float(tr.size)
    return s


class AbsorptionStream:
    """Streaming estimator of absorption/cancel/replenish dynamics at best quotes.

    Parameters
    ----------
    window_s : float  (used only in tests for context; core logic is EMA-based)
    ema_half_life_s : float  half-life for all EMAs
    """

    def __init__(self, window_s: float = 5.0, ema_half_life_s: float = 2.0) -> None:
        self.window_s = float(window_s)
        self.hl = float(ema_half_life_s)
        self.st = _State()
        # Rates (units: volume per second)
        self.sell_mo_rate = _EMA(self.hl)   # hits bid
        self.buy_mo_rate = _EMA(self.hl)    # hits ask
        self.cancel_rate_bid = _EMA(self.hl)
        self.cancel_rate_ask = _EMA(self.hl)
        self.replenish_rate_bid = _EMA(self.hl)
        self.replenish_rate_ask = _EMA(self.hl)

    def update(self, snap: MarketSnapshot) -> Dict[str, float]:
        ts = float(snap.timestamp)
        # initialize
        if self.st.last_ts is None:
            self.st = _State(ts, snap.bid_price, snap.ask_price,
                             float(snap.bid_volumes_l[0]) if snap.bid_volumes_l else 0.0,
                             float(snap.ask_volumes_l[0]) if snap.ask_volumes_l else 0.0)
            return self._features()
        dt = max(1e-6, ts - float(self.st.last_ts))
        # unpack prev
        assert self.st.bid_p is not None and self.st.ask_p is not None, "State not initialized"
        p_b0 = float(self.st.bid_p)
        p_a0 = float(self.st.ask_p)
        q_b0 = float(self.st.bid_q1)
        q_a0 = float(self.st.ask_q1)
        p_b1 = float(snap.bid_price)
        p_a1 = float(snap.ask_price)
        q_b1 = float(snap.bid_volumes_l[0]) if snap.bid_volumes_l else 0.0
        q_a1 = float(snap.ask_volumes_l[0]) if snap.ask_volumes_l else 0.0

        # trades after prev ts
        sell_mo = _sum_trades(snap.trades, Side.SELL, float(self.st.last_ts))
        buy_mo = _sum_trades(snap.trades, Side.BUY, float(self.st.last_ts))

        # --- BID side ---
        cancel_bid = 0.0
        repl_bid = 0.0
        mo_to_bid = 0.0
        if p_b1 == p_b0:
            dq = q_b1 - q_b0
            if dq < -1e-12:
                removal = -dq
                mo_to_bid = min(removal, sell_mo)
                cancel_bid = max(0.0, removal - mo_to_bid)
            elif dq > 1e-12:
                repl_bid = dq
        else:
            # price step: treat previous queue disappearance as depletion event (not attributed)
            if p_b1 < p_b0:
                # bid stepped down → depletion at previous best
                pass
            else:
                # bid stepped up → new liquidity appeared
                repl_bid += q_b1

        # --- ASK side ---
        cancel_ask = 0.0
        repl_ask = 0.0
        mo_to_ask = 0.0
        if p_a1 == p_a0:
            dq = q_a1 - q_a0
            if dq < -1e-12:
                removal = -dq
                mo_to_ask = min(removal, buy_mo)
                cancel_ask = max(0.0, removal - mo_to_ask)
            elif dq > 1e-12:
                repl_ask = dq
        else:
            if p_a1 > p_a0:
                # ask stepped up → depletion at previous best
                pass
            else:
                # ask stepped down → new best with fresh size
                repl_ask += q_a1

        # convert to rates per second
        self.sell_mo_rate.update(mo_to_bid / dt, ts)
        self.buy_mo_rate.update(mo_to_ask / dt, ts)
        self.cancel_rate_bid.update(cancel_bid / dt, ts)
        self.cancel_rate_ask.update(cancel_ask / dt, ts)
        self.replenish_rate_bid.update(repl_bid / dt, ts)
        self.replenish_rate_ask.update(repl_ask / dt, ts)

        # roll state
        self.st.last_ts = ts
        self.st.bid_p = p_b1
        self.st.ask_p = p_a1
        self.st.bid_q1 = q_b1
        self.st.ask_q1 = q_a1

        return self._features()

    # ---------------------- Feature synthesis ----------------------
    def _features(self) -> Dict[str, float]:
        eps = 1e-12
        rem_bid = self.sell_mo_rate.value + self.cancel_rate_bid.value
        rem_ask = self.buy_mo_rate.value + self.cancel_rate_ask.value
        ia_bid = 0.0 if rem_bid <= 0 else self.sell_mo_rate.value / rem_bid
        ia_ask = 0.0 if rem_ask <= 0 else self.buy_mo_rate.value / rem_ask
        resil_bid = self.replenish_rate_bid.value / max(eps, rem_bid)
        resil_ask = self.replenish_rate_ask.value / max(eps, rem_ask)
        pressure_bid = (self.sell_mo_rate.value - self.replenish_rate_bid.value) / max(eps, rem_bid)
        pressure_ask = (self.buy_mo_rate.value - self.replenish_rate_ask.value) / max(eps, rem_ask)
        # TTD proxies
        ttd_bid = float('inf') if (rem_bid - self.replenish_rate_bid.value) <= eps else \
            max(0.0, self.st.bid_q1) / max(eps, (rem_bid - self.replenish_rate_bid.value))
        ttd_ask = float('inf') if (rem_ask - self.replenish_rate_ask.value) <= eps else \
            max(0.0, self.st.ask_q1) / max(eps, (rem_ask - self.replenish_rate_ask.value))
        return {
            # rates per second
            "rate_sell_mo_hit_bid": self.sell_mo_rate.value,
            "rate_buy_mo_hit_ask": self.buy_mo_rate.value,
            "rate_cancel_bid": self.cancel_rate_bid.value,
            "rate_cancel_ask": self.cancel_rate_ask.value,
            "rate_replenish_bid": self.replenish_rate_bid.value,
            "rate_replenish_ask": self.replenish_rate_ask.value,
            # absorption/resilience/pressure
            "absorption_frac_bid": ia_bid,
            "absorption_frac_ask": ia_ask,
            "resilience_bid": resil_bid,
            "resilience_ask": resil_ask,
            "pressure_bid": pressure_bid,
            "pressure_ask": pressure_ask,
            # TTD proxies
            "ttd_bid_s": ttd_bid,
            "ttd_ask_s": ttd_ask,
        }

    # ---------------------- Utility estimators ----------------------
    def estimate_queue_ahead(self, side: Side, horizon_s: float = 0.0) -> float:
        """Queue-ahead estimate for a new LIMIT resting at best now.

        Base estimate uses current best size. If horizon_s>0, we add expected
        replenishment over horizon for that side: q_ahead ≈ q_best + rate_replenish * H.
        """
        if str(side) == str(Side.BUY) or str(side) == "BUY":
            q = max(0.0, self.st.ask_q1)
            add = self.replenish_rate_ask.value * max(0.0, horizon_s)
        else:
            q = max(0.0, self.st.bid_q1)
            add = self.replenish_rate_bid.value * max(0.0, horizon_s)
        return q + add


# =============================
# Self-tests (synthetic)
# =============================

def _mock_stream() -> List[MarketSnapshot]:
    t0 = time.time()
    snaps: List[MarketSnapshot] = []
    bid = 100.00
    ask = 100.02
    qb, qa = 600.0, 620.0
    trades: List[Trade] = []
    for i in range(80):
        ts = t0 + 0.1 * i
        # generate trades: bursts of sellers hit bid on certain steps; buyers hit ask otherwise
        if i % 4 == 1:
            trades.append(Trade(timestamp=ts, price=bid, size=15.0, side=Side.SELL))
        if i % 6 == 2:
            trades.append(Trade(timestamp=ts, price=ask, size=12.0, side=Side.BUY))
        # let queues breathe; ensure some cancels and repl
        if i % 3 == 0:
            qb = max(80.0, qb - 25.0)  # removal at bid
        else:
            qb = min(1000.0, qb + 15.0)  # replenishment
        if i % 5 == 0:
            qa = max(80.0, qa - 30.0)
        else:
            qa = min(1000.0, qa + 12.0)
        # occasional price steps to exercise logic
        if i % 20 == 0 and i > 0:
            bid = round(bid + 0.01, 2)  # bid up
        if i % 24 == 0 and i > 0:
            ask = round(ask + 0.01, 2)  # ask up (depletion prior)
        # snapshot with last 5s trades
        snaps.append(MarketSnapshot(
            timestamp=ts,
            bid_price=bid,
            ask_price=ask,
            bid_volumes_l=[qb, 400, 300, 200, 100],
            ask_volumes_l=[qa, 380, 280, 180, 80],
            trades=tuple(tr for tr in trades if ts - tr.timestamp <= 5.0),
        ))
    return snaps


def _test_absorption_metrics() -> None:
    snaps = _mock_stream()
    ab = AbsorptionStream(window_s=5.0, ema_half_life_s=2.0)
    last = {}
    for s in snaps:
        last = ab.update(s)
    # sanity ranges
    assert 0.0 <= last["absorption_frac_bid"] <= 1.0
    assert 0.0 <= last["absorption_frac_ask"] <= 1.0
    assert last["rate_cancel_bid"] >= 0 and last["rate_cancel_ask"] >= 0
    assert last["rate_replenish_bid"] >= 0 and last["rate_replenish_ask"] >= 0
    assert math.isfinite(last["pressure_bid"]) and math.isfinite(last["pressure_ask"])  # may be negative/positive
    # TTD should be positive finite or inf when replenishment >= removal
    assert last["ttd_bid_s"] >= 0 and last["ttd_ask_s"] >= 0


def _test_queue_ahead() -> None:
    snaps = _mock_stream()
    ab = AbsorptionStream(window_s=5.0, ema_half_life_s=1.5)
    for s in snaps[:10]:
        ab.update(s)
    qa_buy = ab.estimate_queue_ahead(Side.BUY, horizon_s=0.5)
    qa_sell = ab.estimate_queue_ahead(Side.SELL, horizon_s=0.5)
    assert qa_buy > 0 and qa_sell > 0


def _test_absorption_properties() -> None:
    """Test absorption metrics properties and invariants."""
    snaps = _mock_stream()
    ab = AbsorptionStream(window_s=5.0, ema_half_life_s=2.0)
    last = {}
    for s in snaps:
        last = ab.update(s)
    
    # Property: absorption_frac in [0,1]
    assert 0.0 <= last["absorption_frac_bid"] <= 1.0
    assert 0.0 <= last["absorption_frac_ask"] <= 1.0
    
    # Property: ttd >= 0 (can be inf when replenish >= removal)
    assert last["ttd_bid_s"] >= 0 and last["ttd_ask_s"] >= 0
    
    # Property: rates >= 0
    assert last["rate_sell_mo_hit_bid"] >= 0
    assert last["rate_buy_mo_hit_ask"] >= 0
    assert last["rate_cancel_bid"] >= 0
    assert last["rate_cancel_ask"] >= 0
    assert last["rate_replenish_bid"] >= 0
    assert last["rate_replenish_ask"] >= 0


def _test_sell_mo_sensitivity() -> None:
    """Test that increased SELL-MO duration/scale increases pressure_bid."""
    # Create stream with minimal SELL-MO
    snaps_low = _mock_stream()
    ab_low = AbsorptionStream(window_s=5.0, ema_half_life_s=1.0)
    last_low = {}
    for s in snaps_low:
        last_low = ab_low.update(s)
    
    # Create stream with amplified SELL-MO
    t0 = time.time()
    snaps_high: List[MarketSnapshot] = []
    bid = 100.00
    ask = 100.02
    qb, qa = 600.0, 620.0
    trades: List[Trade] = []
    for i in range(80):
        ts = t0 + 0.1 * i
        # Amplified SELL-MO hits
        if i % 4 == 1:
            trades.append(Trade(timestamp=ts, price=bid, size=30.0, side=Side.SELL))  # 3x size
        if i % 6 == 2:
            trades.append(Trade(timestamp=ts, price=ask, size=12.0, side=Side.BUY))
        
        # Same queue dynamics
        if i % 3 == 0:
            qb = max(80.0, qb - 25.0)
        else:
            qb = min(1000.0, qb + 15.0)
        if i % 5 == 0:
            qa = max(80.0, qa - 30.0)
        else:
            qa = min(1000.0, qa + 12.0)
        
        if i % 20 == 0 and i > 0:
            bid = round(bid + 0.01, 2)
        if i % 24 == 0 and i > 0:
            ask = round(ask + 0.01, 2)
        
        snaps_high.append(MarketSnapshot(
            timestamp=ts,
            bid_price=bid,
            ask_price=ask,
            bid_volumes_l=[qb, 400, 300, 200, 100],
            ask_volumes_l=[qa, 380, 280, 180, 80],
            trades=tuple(tr for tr in trades if ts - tr.timestamp <= 5.0),
        ))
    
    ab_high = AbsorptionStream(window_s=5.0, ema_half_life_s=1.0)
    last_high = {}
    for s in snaps_high:
        last_high = ab_high.update(s)
    
    # Higher SELL-MO activity should increase pressure_bid
    assert last_high["pressure_bid"] > last_low["pressure_bid"]


if __name__ == "__main__":
    _test_absorption_metrics()
    _test_queue_ahead()
    _test_absorption_properties()
    _test_sell_mo_sensitivity()
    print("OK - repo/core/features/absorption.py self-tests passed")
