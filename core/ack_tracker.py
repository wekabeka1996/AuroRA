from __future__ import annotations

import time
from typing import Dict, NamedTuple, Callable, Optional, Set


class Pending(NamedTuple):
    t_submit_ns: int
    symbol: str
    cid: str
    side: str
    qty: float


class AckTracker:
    """Simple idempotent tracker for ORDER.SUBMIT awaiting ORDER.ACK.

    If ACK doesn't arrive within ttl_s, emits ORDER.EXPIRE via provided events_emit callable.

    events_emit must support signature: events_emit(event_code: str, details: dict)
    """

    def __init__(self, events_emit: Callable[[str, dict], None], ttl_s: int = 300, scan_period_s: int = 1):
        self.events_emit = events_emit
        self.ttl_ns = int(ttl_s) * 1_000_000_000
        self.scan_period_s = max(0.1, float(scan_period_s))
        self.pending: Dict[str, Pending] = {}
        self.expired: Set[str] = set()
        self._last_scan_ns: int = 0

    def add_submit(self, symbol: str, cid: str, side: str, qty: float, t_submit_ns: Optional[int] = None) -> None:
        if not cid:
            return
        if t_submit_ns is None:
            t_submit_ns = time.time_ns()
        try:
            t_submit_ns = int(t_submit_ns)
        except Exception:
            t_submit_ns = time.time_ns()
        self.pending[cid] = Pending(t_submit_ns, str(symbol), str(cid), str(side), float(qty))

    def ack(self, cid: str) -> None:
        if not cid:
            return
        self.pending.pop(cid, None)

    def scan_once(self, now_ns: Optional[int] = None) -> int:
        now_ns = now_ns or time.time_ns()
        expired_count = 0
        to_expire = [cid for cid, p in list(self.pending.items()) if (now_ns - p.t_submit_ns) > self.ttl_ns]
        for cid in to_expire:
            if cid in self.expired:
                continue
            p = self.pending.pop(cid, None)
            if not p:
                continue
            try:
                self.events_emit(
                    "ORDER.EXPIRE",
                    {
                        "symbol": p.symbol,
                        "cid": p.cid,
                        "side": p.side,
                        "qty": p.qty,
                        "reason_detail": "no ACK within window",
                    },
                )
            except Exception:
                # never raise from scan
                pass
            self.expired.add(cid)
            expired_count += 1
        self._last_scan_ns = int(now_ns)
        return expired_count
