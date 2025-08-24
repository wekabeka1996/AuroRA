from __future__ import annotations

import random
from typing import List, Literal

from core.scalper.trap import BookDelta


def make_neutral_sequence(n: int = 200, *, side: Literal["bid", "ask"] = "bid", start_ts: float = 0.0) -> List[BookDelta]:
    """Balanced add/cancel activity without clear trap signal.

    Produces events already time-sorted to avoid extra work in estimator.
    """
    ts = start_ts
    price = 100.0
    seq: List[BookDelta] = []
    for i in range(n):
        # alternate add/cancel with small variance
        size = 1.0 + 0.1 * random.random()
        if i % 2 == 0:
            seq.append(BookDelta(ts=ts, side=side, price=price, size=size, action="add"))
        else:
            seq.append(BookDelta(ts=ts, side=side, price=price, size=size * 0.9, action="cancel"))
        if i % 10 == 0:
            seq.append(BookDelta(ts=ts, side=side, price=price, size=0.001, action="trade"))
        ts += 0.005
        # jitter price slightly
        price += (random.random() - 0.5) * 0.01
    return seq


def make_fake_wall_sequence(
    *, side: Literal["bid", "ask"] = "ask", depth: int = 5, n: int = 60, burst_ms: int = 200, start_ts: float = 0.0
) -> List[BookDelta]:
    """Create a burst of cancels on one side in a short time window to mimic a fake wall."""
    ts = start_ts
    price = 100.0
    seq: List[BookDelta] = []
    # Fill with some adds first
    for _ in range(depth):
        seq.append(BookDelta(ts=ts, side=side, price=price, size=2.0, action="add"))
        ts += 0.001
    # Rapid cancels within burst window
    step = max(0.001, burst_ms / 1000.0 / max(1, n))
    for _ in range(n):
        seq.append(BookDelta(ts=ts, side=side, price=price, size=2.0, action="cancel"))
        ts += step
    # a few trades
    for _ in range(n // 10):
        seq.append(BookDelta(ts=ts, side=side, price=price, size=0.001, action="trade"))
        ts += 0.001
    return seq


def make_cancel_then_replenish(
    *, side: Literal["bid", "ask"] = "bid", n_cancel: int = 30, n_add: int = 30, delay_ms: float = 20.0, start_ts: float = 0.0
) -> List[BookDelta]:
    """Mass cancel followed by quick repost near best price (cancel→replenish)."""
    ts = start_ts
    price = 100.0
    seq: List[BookDelta] = []
    for _ in range(n_cancel):
        seq.append(BookDelta(ts=ts, side=side, price=price, size=1.5, action="cancel"))
        ts += 0.001
    # small delay then rapid adds
    ts += delay_ms / 1000.0
    for _ in range(n_add):
        # Repost at the same price to register quick replenish latency
        seq.append(BookDelta(ts=ts, side=side, price=price, size=1.5, action="add"))
        ts += 0.001
    # few trades
    for _ in range(max(1, n_cancel // 15)):
        seq.append(BookDelta(ts=ts, side=side, price=price, size=0.002, action="trade"))
        ts += 0.001
    return seq
