from __future__ import annotations

from core.order_lifecycle import lifecycle_state_for


def test_lifecycle_terminal_dedup_and_priority():
    oid = "abc-1"
    events = [
        {"order_id": oid, "status": "CREATED"},
        {"order_id": oid, "status": "SUBMITTED"},
        {"order_id": oid, "status": "ACK"},
        {"order_id": oid, "status": "PARTIAL"},
        {"order_id": oid, "status": "FILLED"},
        # duplicate terminal should not change outcome
        {"order_id": oid, "status": "FILLED"},
    ]
    assert lifecycle_state_for(oid, events) == "FILLED"


def test_lifecycle_unknown_when_no_events():
    assert lifecycle_state_for("x", []) == "UNKNOWN"
