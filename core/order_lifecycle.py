from __future__ import annotations

from typing import Any

TERMINAL = {"FILLED", "CANCELLED", "EXPIRED"}


def lifecycle_state_for(order_id: str, events: list[dict[str, Any]]) -> str:
    """Return lifecycle state for a given order_id based on list of order events.
    Events are dicts with at least {'order_id','status'} or similar.
    Priority: FILLED > CANCELLED > EXPIRED > PARTIAL > ACK > SUBMITTED > CREATED > UNKNOWN
    """
    if not events:
        return "UNKNOWN"
    priority = [
        "FILLED",
        "CANCELLED",
        "EXPIRED",
        "PARTIAL",
        "ACK",
        "SUBMITTED",
        "CREATED",
    ]
    seen = set()
    for ev in events:
        if str(ev.get("order_id") or ev.get("orderId") or "") != str(order_id):
            continue
        s = str(ev.get("status") or ev.get("state") or ev.get("lifecycle") or "").upper()
        if s:
            seen.add(s)
    for s in priority:
        if s in seen:
            return s
    return "UNKNOWN"
