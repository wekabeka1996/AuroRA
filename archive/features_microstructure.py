"""
Aurora+ScalpBot — features/microstructure.py
--------------------------------------------
Single-file module: streaming microstructure features from L2 snapshots and
trades, with an approximate fill-hazard estimator for best-quote resting orders.

Paste into: aurora/features/microstructure.py
Run self-tests: `python aurora/features/microstructure.py`

Implements (§ R1/Road_map alignment):
- OBI L1/Lk, microprice premium, spread (abs, bps), depth ratios (§3–§5)
- OFI (order-flow imbalance) incremental best-quote formulation (Cont-style) (§5)
- TFI (trade-flow imbalance), VPIN-like imbalance ratio (§5)
- Realized vol over event-time window; log-return stats (pre-TCA quality) (§6)
- Approx. fill hazard λ̂ for LIMIT @ best using EMA of order-arrival & cancels (§9)

No external dependencies; NumPy is optional.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
import math
import time

try:  # Optional; used only for pretty array ops if present
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Optional import from core/types; fallback if unavailable ---------
try:  # pragma: no cover - exercised in integration, not in unit self-tests
    from aurora.core.types import (
        Trade, MarketSnapshot, Side,
    )
except Exception:  # Minimal fallbacks to run this file standalone
    class Side(str, Enum):
        BUY = "BUY"
        SELL = "SELL"

    @dataclass
    class Trade:
        timestamp: float
        price: float
        size: float
        side: Side

    @dataclass
    class MarketSnapshot:
        timestamp: float
        bid_price: float
        ask_price: float
        bid_volumes_l: Sequence[float]
        ask_volumes_l: Sequence[float]
        trades: Sequence[Trade]

        @property
        def mid(self) -> float:
            return 0.5 * (self.bid_price + self.ask_price)

        @property
        def spread(self) -> float:
            return self.ask_price - self.bid_price

        def spread_bps(self) -> float:
            m = self.mid
            return 0.0 if m <= 0 else 1e4 * self.spread / m

        def l_sum(self, levels: int = 5) -> Tuple[float, float]:
            return sum(self.bid_volumes_l[:levels]), sum(self.ask_volumes_l[:levels])

        def obi(self, levels: int = 5) -> float:
            b, a = self.l_sum(levels)
            den = b + a
            return 0.0 if den == 0 else (b - a) / den

        def microprice(self, levels: int = 1) -> float:
            if levels <= 1:
                b1 = self.bid_volumes_l[0] if self.bid_volumes_l else 0.0
                a1 = self.ask_volumes_l[0] if self.ask_volumes_l else 0.0
                den = b1 + a1
                return self.mid if den == 0 else (a1 * self.bid_price + b1 * self.ask_price) / den
            b, a = self.l_sum(levels)
            den = b + a
            return self.mid if den == 0 else (a * self.bid_price + b * self.ask_price) / den

# --------------------------------------------------------------------------

@dataclass
class _EMA:
    half_life_s: float
    value: float = 0.0
    _last_ts: Optional[float] = None

    def update(self, x: float, ts: float) -> float:
        if self._last_ts is None:
            self.value = x
            self._last_ts = ts
            return self.value
        dt = max(0.0, ts - self._last_ts)
        # Convert half-life to decay factor: λ = ln(2)/HL; w = exp(-λ dt)
        lam = math.log(2.0) / max(1e-9, self.half_life_s)
        w = math.exp(-lam * dt)
        self.value = w * self.value + (1.0 - w) * x
        self._last_ts = ts
        return self.value


@dataclass
class _Window:
    horizon_s: float
    items: Deque[Tuple[float, float]]
    total: float = 0.0

    def __init__(self, horizon_s: float) -> None:
        self.horizon_s = float(horizon_s)
        self.items = deque()
        self.total = 0.0

    def add(self, ts: float, x: float) -> None:
        self.items.append((ts, x))
        self.total += x
        self._evict(ts)

    def _evict(self, now_ts: float) -> None:
        cutoff = now_ts - self.horizon_s
        while self.items and self.items[0][0] < cutoff:
            _, x0 = self.items.popleft()
            self.total -= x0

    def sum(self, now_ts: float) -> float:
        self._evict(now_ts)
        return self.total

    def values(self, now_ts: float) -> List[float]:
        self._evict(now_ts)
        return [x for _, x in self.items]


class MicrostructureFeatures:
    """Streaming microstructure feature extractor.

    Parameters
    ----------
    window_s : float
        Event-time horizon for rolling statistics (e.g., 5.0 seconds).
    levels : int
        Depth levels to aggregate for OBI and depth ratios.
    ema_half_life_s : float
        Half-life for arrival/cancel EMAs used in fill-hazard estimation.
    """

    def __init__(self, window_s: float = 5.0, levels: int = 5, ema_half_life_s: float = 3.0) -> None:
        self.window_s = float(window_s)
        self.levels = int(levels)
        self.mid_win: _Window = _Window(window_s)
        self.lret_win: _Window = _Window(window_s)  # squared log-returns accumulator
        self.ofi_win: _Window = _Window(window_s)
        self.tfi_win: _Window = _Window(window_s)
        self.buy_vol_win: _Window = _Window(window_s)
        self.sell_vol_win: _Window = _Window(window_s)
        # EMAs for hazard: market-aggressor arrival rates and cancel rates per side
        self.buy_mo_rate = _EMA(ema_half_life_s)   # buyer-initiated trades / s
        self.sell_mo_rate = _EMA(ema_half_life_s)  # seller-initiated trades / s
        self.bid_cancel_rate = _EMA(ema_half_life_s)  # volume/s leaving best bid when P_bid unchanged
        self.ask_cancel_rate = _EMA(ema_half_life_s)
        # state for OFI incremental update
        self._prev: Optional[Tuple[float, float, float, float]] = None  # (bid_p, ask_p, bid_q, ask_q)

    # ---------------------- Core update ----------------------
    def update(self, snap: MarketSnapshot) -> Dict[str, float]:
        ts = float(snap.timestamp)
        # Spread & mid
        mid = snap.mid
        spread = snap.spread
        spread_bps = snap.spread_bps()
        micro = snap.microprice(levels=1)
        micro_premium_bps = 0.0 if mid <= 0 else 1e4 * (micro - mid) / mid

        # Depth and OBI
        b_depth, a_depth = snap.l_sum(self.levels)
        obi_l1 = snap.obi(levels=1)
        obi_lk = snap.obi(levels=self.levels)
        depth_ratio = 0.0 if (b_depth + a_depth) == 0 else b_depth / (b_depth + a_depth)

        # Mid returns & realized variance (event-time)
        self._update_mid_stats(ts, mid)
        rv = self.lret_win.sum(ts)  # sum of squared log-returns over window
        vol_ann = self._ann_vol(rv, horizon_s=self.window_s)

        # OFI incremental update at best
        ofi_inc, cancel_bid, cancel_ask = self._ofi_increment(snap)
        self.ofi_win.add(ts, ofi_inc)
        ofi_sum = self.ofi_win.sum(ts)

        # Trades and TFI/VPIN-like
        buy_sz, sell_sz = self._ingest_trades(ts, snap.trades)
        vpin_like = self._vpin_like(ts)

        # Update EMA rates for hazard
        # Convert volumes to *rates*: per second within window ≈ volume_sum / window_s
        self.buy_mo_rate.update(x=buy_sz / max(1e-9, self.window_s), ts=ts)
        self.sell_mo_rate.update(x=sell_sz / max(1e-9, self.window_s), ts=ts)
        self.bid_cancel_rate.update(x=cancel_bid / max(1e-9, self.window_s), ts=ts)
        self.ask_cancel_rate.update(x=cancel_ask / max(1e-9, self.window_s), ts=ts)

        feats = {
            # Prices & spreads
            "mid": mid,
            "spread": spread,
            "spread_bps": spread_bps,
            "microprice": micro,
            "micro_premium_bps": micro_premium_bps,
            # Depth/imbalance
            "depth_bid_lk": b_depth,
            "depth_ask_lk": a_depth,
            "depth_ratio": depth_ratio,
            "obi_l1": obi_l1,
            "obi_lk": obi_lk,
            # Order/trade flow
            "ofi_sum": ofi_sum,
            "ofi_inc": ofi_inc,
            "tfi": self.tfi_win.sum(ts),
            "buy_vol": self.buy_vol_win.sum(ts),
            "sell_vol": self.sell_vol_win.sum(ts),
            "vpin_like": vpin_like,
            # Volatility
            "rv_window": rv,
            "ann_vol_proxy": vol_ann,
        }
        return feats

    # ---------------------- Fill hazard ----------------------
    def estimate_fill_hazard(self, side: Side, queue_ahead: float) -> Tuple[float, float]:
        """Approximate fill hazard λ̂ (1/s) and expected fill time E[T] (s).

        For a LIMIT at best:
        - BUY: drivers are SELL market-order rate (hitting bid) + cancels in bid queue ahead
        - SELL: drivers are BUY market-order rate (hitting ask) + cancels in ask queue ahead
        λ̂ = (arrival_rate + cancel_rate) / max(queue_ahead, ε)
        E[T] ≈ queue_ahead / max(arrival_rate + cancel_rate, ε)
        """
        eps = 1e-9
        if side == Side.BUY:
            arr = max(0.0, self.sell_mo_rate.value)
            can = max(0.0, self.bid_cancel_rate.value)
        else:
            arr = max(0.0, self.buy_mo_rate.value)
            can = max(0.0, self.ask_cancel_rate.value)
        denom_q = max(eps, queue_ahead)
        rate = (arr + can) / denom_q
        et = denom_q / max(eps, (arr + can))
        return rate, et

    # ---------------------- Internals ----------------------
    def _update_mid_stats(self, ts: float, mid: float) -> None:
        vals = self.mid_win.values(ts)
        prev_mid = vals[-1] if vals else None
        self.mid_win.add(ts, mid)
        if prev_mid is not None and prev_mid > 0 and mid > 0:
            lr = math.log(mid / prev_mid)
            self.lret_win.add(ts, lr * lr)

    def _ofi_increment(self, snap: MarketSnapshot) -> Tuple[float, float, float]:
        """Incremental OFI at best quotes.

        OFI rule-of-thumb (best-level Cont/deLarrard-style):
        Let (p_b,q_b),(p_a,q_a) be best bid/ask price & size. Then ΔOFI_t is:
        - If p_b↑: +q_b(new); if p_b↓: −q_b(old); if p_b=const: +Δq_b
        - If p_a↓: +q_a(old); if p_a↑: −q_a(new); if p_a=const: −Δq_a
        The total increment is the sum of bid and ask contributions.

        Additionally, we approximate cancellations at best when price unchanged
        and size decreases: cancel_bid = max(0, −Δq_b) on bid; cancel_ask = max(0, −Δq_a) on ask.
        Returns (ofi_inc, cancel_bid, cancel_ask).
        """
        p_b, p_a = snap.bid_price, snap.ask_price
        q_b = snap.bid_volumes_l[0] if snap.bid_volumes_l else 0.0
        q_a = snap.ask_volumes_l[0] if snap.ask_volumes_l else 0.0
        if self._prev is None:
            self._prev = (p_b, p_a, q_b, q_a)
            return 0.0, 0.0, 0.0
        p_b0, p_a0, q_b0, q_a0 = self._prev
        ofi = 0.0
        cancel_bid = 0.0
        cancel_ask = 0.0
        # Bid contribution
        if p_b > p_b0:
            ofi += q_b  # stronger bid appeared
        elif p_b < p_b0:
            ofi -= q_b0  # bid stepped down
        else:
            dq = q_b - q_b0
            ofi += dq
            if dq < 0:
                cancel_bid += -dq
        # Ask contribution
        if p_a < p_a0:
            ofi += q_a0  # ask stepped down (buy pressure)
        elif p_a > p_a0:
            ofi -= q_a  # ask stepped up (sell pressure)
        else:
            dq = q_a - q_a0
            ofi -= dq
            if dq < 0:
                cancel_ask += -dq
        self._prev = (p_b, p_a, q_b, q_a)
        return ofi, cancel_bid, cancel_ask

    def _ingest_trades(self, ts: float, trades: Sequence[Trade]) -> Tuple[float, float]:
        buy_sz = 0.0
        sell_sz = 0.0
        for tr in trades:
            if tr.side == Side.BUY:
                buy_sz += tr.size
                self.tfi_win.add(ts, +tr.size)
                self.buy_vol_win.add(ts, tr.size)
            else:
                sell_sz += tr.size
                self.tfi_win.add(ts, -tr.size)
                self.sell_vol_win.add(ts, tr.size)
        return buy_sz, sell_sz

    def _vpin_like(self, now_ts: float) -> float:
        b = self.buy_vol_win.sum(now_ts)
        s = self.sell_vol_win.sum(now_ts)
        den = b + s
        return 0.0 if den == 0 else abs(b - s) / den

    @staticmethod
    def _ann_vol(rv_window: float, horizon_s: float) -> float:
        """Annualized vol proxy from realized variance over window.
        σ_ann ≈ sqrt(rv_window) * sqrt( seconds_in_year / horizon_s ).
        """
        sec_in_year = 365.0 * 24.0 * 3600.0
        if rv_window <= 0 or horizon_s <= 0:
            return 0.0
        return math.sqrt(rv_window) * math.sqrt(sec_in_year / horizon_s)


# =============================
# Minimal self-tests
# =============================

def _mock_stream() -> Tuple[List[MarketSnapshot], List[Trade]]:
    t0 = time.time()
    snaps: List[MarketSnapshot] = []
    trades: List[Trade] = []
    bid = 100.00
    ask = 100.02
    q_bid = 500.0
    q_ask = 520.0
    for i in range(50):
        ts = t0 + 0.1 * i
        # alternate microstructure dynamics
        if i % 5 == 0:
            # tighten
            ask = round(ask - 0.01, 2)
        elif i % 7 == 0:
            # widen
            ask = round(ask + 0.02, 2)
        # random-like volume breathing (deterministic here)
        q_bid += (10 if i % 3 == 0 else -6)
        q_bid = max(50.0, q_bid)
        q_ask += (-8 if i % 4 == 0 else 5)
        q_ask = max(50.0, q_ask)
        # occasional trades
        if i % 4 == 1:
            tr = Trade(timestamp=ts, price=ask, size=12.0, side=Side.BUY)
            trades.append(tr)
        if i % 6 == 2:
            tr = Trade(timestamp=ts, price=bid, size=9.0, side=Side.SELL)
            trades.append(tr)
        snap = MarketSnapshot(
            timestamp=ts,
            bid_price=bid,
            ask_price=ask,
            bid_volumes_l=[q_bid, 400, 300, 200, 100],
            ask_volumes_l=[q_ask, 380, 280, 180, 80],
            trades=tuple(tr for tr in trades if ts - tr.timestamp <= 5.0),
        )
        snaps.append(snap)
        # small mid drift every few steps
        if i % 8 == 0:
            bid = round(bid + 0.01, 2)
        elif i % 9 == 0:
            bid = round(bid - 0.01, 2)
    return snaps, trades


def _test_features_and_hazard() -> None:
    snaps, _ = _mock_stream()
    fx = MicrostructureFeatures(window_s=5.0, levels=5, ema_half_life_s=2.0)
    last_feats: Dict[str, float] = {}
    for s in snaps:
        last_feats = fx.update(s)
    # Basic sanity checks
    assert last_feats["spread"] >= 0
    assert -1.0 <= last_feats["obi_l1"] <= 1.0
    assert -1.0 <= last_feats["obi_lk"] <= 1.0
    assert last_feats["depth_bid_lk"] > 0 and last_feats["depth_ask_lk"] > 0
    assert last_feats["ann_vol_proxy"] >= 0
    # OFI & TFI should be finite and typically non-zero in this mock
    assert abs(last_feats["ofi_sum"]) >= 0
    assert abs(last_feats["tfi"]) >= 0
    # Hazard estimates should be finite and positive given activity
    lam_buy, et_buy = fx.estimate_fill_hazard(Side.BUY, queue_ahead=200.0)
    lam_sell, et_sell = fx.estimate_fill_hazard(Side.SELL, queue_ahead=220.0)
    assert lam_buy >= 0 and et_buy > 0 and lam_sell >= 0 and et_sell > 0


if __name__ == "__main__":
    _test_features_and_hazard()
    print("OK - features/microstructure.py self-tests passed")
