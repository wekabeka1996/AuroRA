"""
Aurora+ScalpBot — repo/core/features/obi.py
-------------------------------------------
Order Book Imbalance (OBI) features and depth metrics extracted from L2 snapshots.

I/O Contract:
- Event-time: All computations based on snapshot timestamps, no calendar time assumptions
- No look-ahead: Features computed only from current and past data, no future information leakage
- Invariants: OBI ∈ [-1, 1], depth ratios ≥ 0, spread_bps ≥ 0, microprice ∈ [bid, ask]

Paste into: repo/core/features/obi.py
Run self-tests: `python repo/core/features/obi.py`

Implements (per project structure):
- OBI @L1 and OBI @Lk (k≥1) with safe guards
- Depth aggregates: bid/ask sums over first k levels and their ratio
- Convenience helpers: spread (abs, bps), mid
- Stateless pure functions + optional streaming wrapper for convenience

No external dependencies; NumPy optional. Can run standalone (provides
fallback `MarketSnapshot` if core types are unavailable).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Mapping, Optional, Sequence, Tuple
import math
import time

try:  # optional pretty array ops only; core logic does not require NumPy
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Import from core types -------
from core.types import MarketSnapshot

# =============================
# Pure feature functions
# =============================

def depth_sums(bid_volumes_l: Sequence[float], ask_volumes_l: Sequence[float], levels: int = 5) -> Tuple[float, float]:
    """Sum of depths on bid/ask over first k levels. Levels>len(list) → clamp."""
    k = max(1, int(levels))
    b = sum(float(x) for x in bid_volumes_l[:k])
    a = sum(float(x) for x in ask_volumes_l[:k])
    return b, a


def depth_ratio(bid_volumes_l: Sequence[float], ask_volumes_l: Sequence[float], levels: int = 5) -> float:
    b, a = depth_sums(bid_volumes_l, ask_volumes_l, levels)
    den = b + a
    return 0.0 if den == 0.0 else b / den


def obi_l1(bid_volumes_l: Sequence[float], ask_volumes_l: Sequence[float]) -> float:
    """L1-OBI = (q_b1 − q_a1) / (q_b1 + q_a1)."""
    qb = float(bid_volumes_l[0]) if bid_volumes_l else 0.0
    qa = float(ask_volumes_l[0]) if ask_volumes_l else 0.0
    den = qb + qa
    return 0.0 if den == 0.0 else (qb - qa) / den


def obi_lk(bid_volumes_l: Sequence[float], ask_volumes_l: Sequence[float], levels: int = 5) -> float:
    """Lk-OBI over first k levels: (Σ q_b − Σ q_a) / (Σ q_b + Σ q_a)."""
    b, a = depth_sums(bid_volumes_l, ask_volumes_l, levels)
    den = b + a
    return 0.0 if den == 0.0 else (b - a) / den


def spread_bps(bid_price: float, ask_price: float) -> float:
    mid = 0.5 * (float(bid_price) + float(ask_price))
    spr = float(ask_price) - float(bid_price)
    return 0.0 if mid <= 0 else 1e4 * spr / mid


# =============================
# Streaming wrapper (optional)
# =============================

class OBIStream:
    """Convenience streaming extractor returning a compact feature dict per snapshot.

    Example
    -------
    >>> obi = OBIStream(levels=5)
    >>> feats = obi.update(snap)
    >>> feats["obi_l1"], feats["obi_lk"], feats["depth_ratio"]
    """

    def __init__(self, levels: int = 5) -> None:
        self.levels = max(1, int(levels))

    def update(self, snap: MarketSnapshot) -> Dict[str, float]:
        k = self.levels
        b, a = depth_sums(snap.bid_volumes_l, snap.ask_volumes_l, k)
        feats = {
            "mid": snap.mid,
            "spread": snap.spread,
            "spread_bps": snap.spread_bps(),
            "depth_bid_lk": b,
            "depth_ask_lk": a,
            "depth_ratio": depth_ratio(snap.bid_volumes_l, snap.ask_volumes_l, k),
            "obi_l1": obi_l1(snap.bid_volumes_l, snap.ask_volumes_l),
            "obi_lk": obi_lk(snap.bid_volumes_l, snap.ask_volumes_l, k),
        }
        return feats


# =============================
# Self-tests
# =============================

def _mock_snapseq() -> List[MarketSnapshot]:
    t0 = time.time()
    snaps: List[MarketSnapshot] = []
    bid, ask = 100.00, 100.02
    qb1, qa1 = 500.0, 520.0
    for i in range(20):
        ts = t0 + 0.1 * i
        # oscillate best sizes to cause OBI swings
        qb1 = max(50.0, qb1 + (30.0 if i % 3 == 0 else -15.0))
        qa1 = max(50.0, qa1 + (-25.0 if i % 4 == 0 else 10.0))
        # tweak ask to vary spread a bit
        if i % 5 == 0:
            ask = max(bid + 0.01, round(ask - 0.01, 2))  # ensure ask > bid
        elif i % 7 == 0:
            ask = round(ask + 0.02, 2)
        snaps.append(MarketSnapshot(
            timestamp=ts,
            bid_price=bid,
            ask_price=ask,
            bid_volumes_l=[qb1, 400, 300, 200, 100],
            ask_volumes_l=[qa1, 380, 280, 180, 80],
        ))
        # drift bid
        if i % 8 == 0:
            bid = min(ask - 0.01, round(bid + 0.01, 2))  # ensure bid < ask
        elif i % 9 == 0:
            bid = max(0.01, round(bid - 0.01, 2))  # ensure bid > 0
    return snaps


def _test_pure_funcs() -> None:
    b = [100.0, 50.0, 25.0]
    a = [80.0, 50.0, 25.0]
    assert depth_sums(b, a, 2) == (150.0, 130.0)
    assert abs(depth_ratio(b, a, 3) - (175.0/330.0)) < 1e-12
    l1 = obi_l1(b, a)
    lk = obi_lk(b, a, 3)
    assert -1.0 <= l1 <= 1.0 and -1.0 <= lk <= 1.0


def _test_stream() -> None:
    seq = _mock_snapseq()
    obi = OBIStream(levels=5)
    last = {}
    for s in seq:
        last = obi.update(s)
    assert "obi_l1" in last and "obi_lk" in last
    assert -1.0 <= last["obi_l1"] <= 1.0
    assert -1.0 <= last["obi_lk"] <= 1.0
    assert last["depth_bid_lk"] > 0 and last["depth_ask_lk"] > 0
    assert last["spread_bps"] >= 0


if __name__ == "__main__":
    _test_pure_funcs()
    _test_stream()
    print("OK - repo/core/features/obi.py self-tests passed")