"""
Aurora+ScalpBot — repo/core/features/tfi.py
-------------------------------------------
Trade-Flow Imbalance (TFI) features on event-time windows, plus VPIN-like
imbalance ratio and a volume-bucket VPIN estimator.

I/O Contract:
- Event-time: All computations based on trade timestamps, no calendar time assumptions
- No look-ahead: Features computed only from current and past trades, no future information leakage
- Invariants: TFI ∈ [-∞, ∞], VPIN ∈ [0, 1], volume-bucket VPIN ignores incomplete buckets

Paste into: repo/core/features/tfi.py
Run self-tests: `python repo/core/features/tfi.py`

Implements (per project structure):
- Event-time rolling TFI: sum(+size for BUY, −size for SELL) over last window_s
- Rolling buy/sell volumes and VPIN-like ratio: |B−S| / (B+S)
- Volume-bucket VPIN (Easley/Lopez de Prado style, simplified):
    VPIN ≈ (1/N) * Σ |B_i − S_i| / V, with fixed bucket volume V, last N buckets
- Stateless pure helpers + streaming class `TFIStream`

No external dependencies; NumPy optional. Provides fallback `Trade`/`Side` when
`aurora.core.types` is unavailable.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Tuple
import math
import time

try:  # optional, used only if available
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Import from core types -------
from core.types import Trade, Side

# =============================
# Pure helpers
# =============================

def tfi_increment(tr: Trade) -> float:
    """+size for BUY taker, −size for SELL taker."""
    return float(tr.size) if str(tr.side) == "Side.BUY" or str(tr.side) == "BUY" else -float(tr.size)


def vpin_like(buy_vol: float, sell_vol: float) -> float:
    den = float(buy_vol) + float(sell_vol)
    if den <= 0.0:
        return 0.0
    return abs(float(buy_vol) - float(sell_vol)) / den


def vpin_volume_buckets(trades: Sequence[Trade], bucket_volume: float, max_buckets: int = 50) -> float:
    """Simplified VPIN: partition stream into successive buckets of fixed volume V.

    For each bucket i, accumulate BUY and SELL volumes until reaching V. The
    bucket imbalance is |B_i − S_i| / V (capped at 1). VPIN is the average over
    the last N=min(max_buckets, #buckets) buckets.
    """
    if bucket_volume <= 0.0:
        return 0.0

    V = max(1e-9, float(bucket_volume))
    B = 0.0
    S = 0.0
    imbalances: List[float] = []
    for tr in trades:
        # how much of trade fits into current bucket
        remain = V - (B + S)
        vol = float(tr.size)
        side = tr.side
        while vol > 0.0:
            take = min(remain, vol)
            if str(side) == "Side.BUY" or str(side) == "BUY":
                B += take
            else:
                S += take
            vol -= take
            remain -= take
            # bucket complete
            if remain <= 0.0:
                imbalances.append(min(1.0, abs(B - S) / V))
                B, S = 0.0, 0.0
                remain = V
    # if last partial bucket exists but not full, ignore it (standard practice)
    if not imbalances:
        return 0.0
    n = min(int(max_buckets), len(imbalances))
    return sum(imbalances[-n:]) / n


# =============================
# Streaming class
# =============================

class TFIStream:
    """Streaming TFI/VPIN extractor on event-time window.

    Parameters
    ----------
    window_s : float
        Event-time horizon for rolling sums (default 5.0 seconds).
    bucket_volume : float
        Volume per VPIN bucket (same units as trade size). If <=0, VPIN buckets
        are disabled and only VPIN-like ratio is returned.
    max_trades : int
        Hard cap on trades retained for VPIN-bucket computation.
    """
    def __init__(self, window_s: float = 5.0, bucket_volume: float = 100.0, max_trades: int = 5000) -> None:
        self.win = _Rolling(window_s)
        self.bucket_volume = float(bucket_volume)
        self.max_trades = int(max_trades)
        self._trades: Deque[Trade] = deque()

    def ingest_trade(self, tr: Trade) -> None:
        ts = float(tr.timestamp)
        buy = float(tr.size) if str(tr.side) == "Side.BUY" or str(tr.side) == "BUY" else 0.0
        sell = float(tr.size) if str(tr.side) == "Side.SELL" or str(tr.side) == "SELL" else 0.0
        self.win.add(ts, buy=buy, sell=sell)
        # store for VPIN-bucket (cap by count and evict by time horizon generously)
        self._trades.append(tr)
        while len(self._trades) > self.max_trades:
            self._trades.popleft()
        # also time-based cleanup to keep fresh
        cutoff = ts - 10.0 * self.win.h  # keep at most 10×window for bucket VPIN context
        while self._trades and float(self._trades[0].timestamp) < cutoff:
            self._trades.popleft()

    def features(self, now_ts: Optional[float] = None) -> Dict[str, float]:
        if now_ts is None:
            now_ts = time.time()
        b, s = self.win.sums(now_ts)
        tfi = b - s
        feats = {
            "buy_vol": b,
            "sell_vol": s,
            "tfi": tfi,
            "vpin_like": vpin_like(b, s),
        }
        if self.bucket_volume > 0.0 and self._trades:
            feats["vpin_bucketed"] = vpin_volume_buckets(list(self._trades), self.bucket_volume, max_buckets=50)
        else:
            feats["vpin_bucketed"] = 0.0
        return feats


@dataclass
class _WinTrade:
    ts: float
    buy: float
    sell: float


class _Rolling:
    """Rolling event-time window for buy/sell volumes with O(1) evictions."""
    def __init__(self, horizon_s: float) -> None:
        self.h = float(horizon_s)
        self.q: Deque[_WinTrade] = deque()
        self.bsum = 0.0
        self.ssum = 0.0

    def add(self, ts: float, buy: float, sell: float) -> None:
        self.q.append(_WinTrade(ts=ts, buy=buy, sell=sell))
        self.bsum += buy
        self.ssum += sell
        self._evict(ts)

    def _evict(self, now_ts: float) -> None:
        if self.h <= 0.0:
            # Zero or negative horizon means evict everything
            while self.q:
                t = self.q.popleft()
                self.bsum -= t.buy
                self.ssum -= t.sell
        else:
            cutoff = float(now_ts) - self.h
            while self.q and self.q[0].ts < cutoff:
                t = self.q.popleft()
                self.bsum -= t.buy
                self.ssum -= t.sell

    def sums(self, now_ts: float) -> Tuple[float, float]:
        self._evict(now_ts)
        return self.bsum, self.ssum


# =============================
# Self-tests (synthetic)
# =============================

def _make_trades_imbalanced(n: int = 200, seed: int = 1) -> List[Trade]:
    import random
    random.seed(seed)
    t0 = time.time()
    out: List[Trade] = []
    ts = t0
    for i in range(n):
        # 70% buys, 30% sells, sizes around 10±3
        is_buy = (random.random() < 0.7)
        size = max(0.1, 10.0 + random.gauss(0.0, 3.0))
        ts += max(0.0, random.expovariate(20.0))
        out.append(Trade(timestamp=ts, price=100.0, size=size, side=Side.BUY if is_buy else Side.SELL))
    return out


def _make_trades_balanced(n: int = 200, seed: int = 2) -> List[Trade]:
    import random
    random.seed(seed)
    t0 = time.time()
    out: List[Trade] = []
    ts = t0
    for i in range(n):
        is_buy = (i % 2 == 0)
        size = max(0.1, 10.0 + random.gauss(0.0, 3.0))
        ts += max(0.0, random.expovariate(20.0))
        out.append(Trade(timestamp=ts, price=100.0, size=size, side=Side.BUY if is_buy else Side.SELL))
    return out


def _test_event_time_tfi_vpin() -> None:
    tr = _make_trades_imbalanced()
    tfi = TFIStream(window_s=2.0, bucket_volume=100.0)
    for x in tr:
        tfi.ingest_trade(x)
    feats = tfi.features(now_ts=tr[-1].timestamp)
    assert feats["buy_vol"] > feats["sell_vol"]
    assert feats["tfi"] > 0
    assert 0.0 <= feats["vpin_like"] <= 1.0
    assert 0.0 <= feats["vpin_bucketed"] <= 1.0


def _test_vpin_contrast() -> None:
    tr_imbal = _make_trades_imbalanced(seed=11)
    tr_bal = _make_trades_balanced(seed=22)
    vpin_imbal = vpin_volume_buckets(tr_imbal, bucket_volume=100.0, max_buckets=50)
    vpin_bal = vpin_volume_buckets(tr_bal, bucket_volume=100.0, max_buckets=50)
    # Imbalanced stream should have higher VPIN than balanced
    assert vpin_imbal >= vpin_bal - 1e-6


if __name__ == "__main__":
    _test_event_time_tfi_vpin()
    _test_vpin_contrast()
    print("OK - repo/core/features/tfi.py self-tests passed")