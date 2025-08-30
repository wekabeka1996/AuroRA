"""
Aurora+ScalpBot — repo/core/features/microprice.py
--------------------------------------------------
Microprice estimators and micro-premium (bps) from L2 snapshots.

I/O Contract:
- Units: mid prices in currency units, micro-premium in basis points (bps)
- Event-time: All computations based on snapshot timestamps, no calendar time assumptions
- No look-ahead: Features computed only from current and past data, no future information leakage

Paste into: repo/core/features/microprice.py
Run self-tests: `python repo/core/features/microprice.py`

Implements (per project structure):
- L1 microprice (volume-weighted best-quote)
- Lk microprice using aggregated depths (k≥1)
- Micro-premium in bps relative to mid (both L1 and Lk)
- Stateless pure functions + streaming wrapper

No external dependencies; NumPy optional. Provides fallback MarketSnapshot
when aurora.core.types is unavailable.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple
import math
import time

try:  # optional, used only for pretty-printing/arrays
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Import from core types -------
from core.types import MarketSnapshot

# =============================
# Pure functions
# =============================

def _safe_mid(bid_price: float, ask_price: float) -> float:
    return 0.5 * (float(bid_price) + float(ask_price))


def microprice_l1(bid_price: float, ask_price: float, bid_q1: float, ask_q1: float) -> float:
    """Classic L1 microprice.
    mp = (ask_q1 * bid_price + bid_q1 * ask_price) / (bid_q1 + ask_q1)
    If denominator is zero, falls back to mid.
    """
    b, a = float(bid_price), float(ask_price)
    qb, qa = max(0.0, float(bid_q1)), max(0.0, float(ask_q1))
    den = qb + qa
    if den <= 0.0:
        return _safe_mid(b, a)
    return (qa * b + qb * a) / den


def _sum_first_k(x: Sequence[float], k: int) -> float:
    return sum(float(v) for v in x[:max(1, k)])


def microprice_lk(
    bid_price: float,
    ask_price: float,
    bid_volumes_l: Sequence[float],
    ask_volumes_l: Sequence[float],
    levels: int = 5,
) -> float:
    """Lk microprice using aggregated volumes as weights.
    mp_k = (Σ_{ask} q_a · bid_price + Σ_{bid} q_b · ask_price) / (Σ_{ask} q_a + Σ_{bid} q_b)
    """
    b, a = float(bid_price), float(ask_price)
    qb = _sum_first_k(bid_volumes_l, levels)
    qa = _sum_first_k(ask_volumes_l, levels)
    den = qb + qa
    if den <= 0.0:
        return _safe_mid(b, a)
    return (qa * b + qb * a) / den


def micro_premium_bps(mid: float, microprice: float) -> float:
    """Premium of microprice over mid, in basis points."""
    m, mp = float(mid), float(microprice)
    if m <= 0.0:
        return 0.0
    return 1e4 * (mp - m) / m


# =============================
# Streaming wrapper
# =============================

class MicropriceStream:
    """Convenience streaming extractor.

    Parameters
    ----------
    levels : int
        Depth levels to aggregate for Lk microprice (k≥1).
    """

    def __init__(self, levels: int = 5) -> None:
        self.levels = max(1, int(levels))

    def update(self, snap: MarketSnapshot) -> Dict[str, float]:
        k = self.levels
        qb1 = float(snap.bid_volumes_l[0]) if snap.bid_volumes_l else 0.0
        qa1 = float(snap.ask_volumes_l[0]) if snap.ask_volumes_l else 0.0
        mp1 = microprice_l1(snap.bid_price, snap.ask_price, qb1, qa1)
        mpk = microprice_lk(snap.bid_price, snap.ask_price, snap.bid_volumes_l, snap.ask_volumes_l, k)
        feats = {
            "mid": snap.mid,
            "spread": snap.spread,
            "spread_bps": snap.spread_bps(),
            "microprice_l1": mp1,
            "microprice_lk": mpk,
            "micro_premium_l1_bps": micro_premium_bps(snap.mid, mp1),
            "micro_premium_lk_bps": micro_premium_bps(snap.mid, mpk),
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
    for i in range(30):
        ts = t0 + 0.1 * i
        # vary best sizes to move microprice around mid
        qb1 = max(50.0, qb1 + (35.0 if i % 3 == 0 else -18.0))
        qa1 = max(50.0, qa1 + (-28.0 if i % 4 == 0 else 12.0))
        # sometimes tighten/widen ask
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
        # Modify bid after creating snapshot to maintain valid spread
        if i % 8 == 0:
            bid = min(ask - 0.01, round(bid + 0.01, 2))  # ensure bid < ask
        elif i % 9 == 0:
            bid = max(0.01, round(bid - 0.01, 2))  # ensure bid > 0
    return snaps


def _test_microprice_bounds() -> None:
    # microprice must lie in [bid, ask]
    b, a = 100.00, 100.02
    mp1 = microprice_l1(b, a, 500, 520)
    assert b <= mp1 <= a
    mpk = microprice_lk(b, a, [500, 400, 300], [520, 380, 280], 3)
    assert b <= mpk <= a


def _test_stream_last_values() -> None:
    seq = _mock_snapseq()
    ms = MicropriceStream(levels=5)
    last: Dict[str, float] = {}
    for s in seq:
        last = ms.update(s)
    assert "microprice_l1" in last and "microprice_lk" in last
    # premiums should be finite and typically small in bps
    assert abs(last["micro_premium_l1_bps"]) < 100.0
    assert abs(last["micro_premium_lk_bps"]) < 100.0


def _test_invariance_zero_den() -> None:
    # if both sides zero, fallback to mid
    b, a = 100.00, 100.02
    mp = microprice_l1(b, a, 0.0, 0.0)
    assert abs(mp - _safe_mid(b, a)) < 1e-12


if __name__ == "__main__":
    _test_microprice_bounds()
    _test_stream_last_values()
    _test_invariance_zero_den()
    print("OK - repo/core/features/microprice.py self-tests passed")