from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


def _percentiles(values: List[float], qs: List[int]) -> Dict[int, float]:
    if not values:
        return {q: 0.0 for q in qs}
    arr = sorted(values)
    out: Dict[int, float] = {}
    n = len(arr)
    for q in qs:
        # nearest-rank
        k = max(1, min(n, int((q / 100.0) * n + 0.9999)))
        out[q] = float(arr[k - 1])
    return out


@dataclass
class OrderState:
    cid: Optional[str] = None
    oid: Optional[str] = None
    submit_ns: Optional[int] = None
    ack_ns: Optional[int] = None
    done_ns: Optional[int] = None
    final: Optional[str] = None  # FILLED/CANCELED/REJECTED/EXPIRED
    fills: int = 0
    qty_filled: float = 0.0


class LifecycleCorrelator:
    def __init__(self, window_s: int = 300):
        self.window_ns = int(window_s * 1_000_000_000)
        self.by_cid: Dict[str, OrderState] = {}
        self.by_oid: Dict[str, OrderState] = {}

    def add_event(self, ev: Dict[str, Any]) -> None:
        cid = ev.get("cid")
        oid = ev.get("oid")
        ts_ns = int(ev.get("ts_ns") or 0)
        etype = str(ev.get("type") or ev.get("event") or ev.get("code") or "")
        state = None
        if cid and cid in self.by_cid:
            state = self.by_cid[cid]
        elif oid and oid in self.by_oid:
            state = self.by_oid[oid]
        else:
            state = OrderState(cid=cid, oid=oid)
            if cid:
                self.by_cid[cid] = state
            if oid:
                self.by_oid[oid] = state
        # correlate oid once ACK received
        if not state.oid and oid:
            state.oid = oid
            self.by_oid[oid] = state
        # Normalize both dot and underscore notations, e.g., ORDER.SUBMIT vs ORDER_SUBMIT
        u = etype.upper().replace('.', '_')
        if u.endswith("ORDER_SUBMIT") or u == "ORDER_SUBMIT":
            state.submit_ns = ts_ns
        elif u.endswith("ORDER_ACK") or u == "ORDER_ACK":
            # if submit missing, still record ack
            state.ack_ns = ts_ns
        elif u.endswith("ORDER_PARTIAL") or u == "ORDER_PARTIAL":
            state.fills += 1
            q = ev.get("fill_qty") or ev.get("qty")
            try:
                if q is not None:
                    state.qty_filled += float(q)
            except Exception:
                pass
        elif u.endswith("ORDER_FILL") or u == "ORDER_FILL":
            state.fills += 1
            q = ev.get("fill_qty") or ev.get("qty")
            try:
                if q is not None:
                    state.qty_filled += float(q)
            except Exception:
                pass
            state.final = "FILLED"
            state.done_ns = ts_ns
        elif u.endswith("ORDER_CANCEL") or u == "ORDER_CANCEL":
            state.final = "CANCELED"
            state.done_ns = ts_ns
        elif u.endswith("ORDER_REJECT") or u == "ORDER_REJECT":
            state.final = "REJECTED"
            state.done_ns = ts_ns
        elif u.endswith("ORDER_EXPIRE") or u == "ORDER_EXPIRE":
            state.final = "EXPIRED"
            state.done_ns = ts_ns

    def finalize(self, now_ns: Optional[int] = None) -> Dict[str, Any]:
        if now_ns is None:
            import time as _t
            now_ns = int(_t.time() * 1_000_000_000)
        submit_ack_ms: List[float] = []
        ack_done_ms: List[float] = []
        orders: Dict[str, Any] = {}
        for cid, st in self.by_cid.items():
            # expire dangling submits without ACK within window
            if st.final is None:
                if st.submit_ns is not None and (now_ns - st.submit_ns) > self.window_ns and st.ack_ns is None:
                    st.final = "EXPIRED"
                    st.done_ns = st.submit_ns + self.window_ns
            if st.submit_ns and st.ack_ns:
                submit_ack_ms.append((st.ack_ns - st.submit_ns) / 1_000_000.0)
            if st.ack_ns and st.done_ns:
                ack_done_ms.append((st.done_ns - st.ack_ns) / 1_000_000.0)
            orders[cid] = {
                "oid": st.oid,
                "final": st.final,
                "submit_ts_ns": st.submit_ns,
                "ack_ts_ns": st.ack_ns,
                "done_ts_ns": st.done_ns,
                "fills": st.fills,
                "qty_filled": st.qty_filled,
            }
        def _mk(buckets: List[float]) -> Dict[str, float]:
            pct = _percentiles(buckets, [50, 95, 99])
            return {"p50": pct[50], "p95": pct[95], "p99": pct[99]}
        return {
            "orders": orders,
            "latency_ms": {
                "submit_ack": _mk(submit_ack_ms),
                "ack_done": _mk(ack_done_ms),
            },
        }
