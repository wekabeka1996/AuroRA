from __future__ import annotations

import json
from pathlib import Path

from core.aurora_event_logger import AuroraEventLogger


def read_jsonl(p: Path):
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]


def test_emit_order_events_and_idempotency(tmp_path: Path):
    p = tmp_path / "aurora_events.jsonl"
    logger = AuroraEventLogger(path=p)
    details = {"symbol": "BTCUSDT", "cid": "C1", "side": "BUY", "order_type": "LIMIT", "price": 100.0, "qty": 1.0}
    # underscore input should be normalized to dotted code
    logger.emit("ORDER_SUBMIT", {**details, "ts_ns": 1})
    logger.emit("ORDER.ACK", {**details, "oid": "O1", "ts_ns": 2})
    logger.emit("ORDER.PARTIAL", {**details, "oid": "O1", "fill_qty": 0.5, "ts_ns": 3})
    logger.emit("ORDER.FILL", {**details, "oid": "O1", "fill_qty": 0.5, "ts_ns": 4})
    # duplicates (same key) should be ignored
    logger.emit("ORDER.ACK", {**details, "oid": "O1", "ts_ns": 2})
    rows = read_jsonl(p)
    codes = [r["event_code"] for r in rows]
    assert "ORDER.SUBMIT" in codes and "ORDER.ACK" in codes and "ORDER.PARTIAL" in codes and "ORDER.FILL" in codes
    # underscore normalized
    assert any(r for r in rows if r["event_code"] == "ORDER.SUBMIT")
    # idempotency: duplicate not appended
    ts2 = [r for r in rows if r.get("ts_ns") == 2]
    assert len(ts2) == 1


def test_cancel_and_expire_events(tmp_path: Path):
    from core.ack_tracker import AckTracker

    p = tmp_path / "aurora_events.jsonl"
    logger = AuroraEventLogger(path=p)

    # Cancel request/ack should be accepted by emitter
    details = {"symbol": "BTCUSDT", "cid": "C2", "side": "SELL", "qty": 0.1}
    logger.emit("ORDER.CANCEL.REQUEST", {**details, "ts_ns": 10})
    logger.emit("ORDER.CANCEL.ACK", {**details, "oid": "O2", "ts_ns": 11})

    # AckTracker should emit ORDER.EXPIRE when ACK does not arrive within ttl
    emitted: list[dict] = []
    def _capture(code: str, d: dict):
        # also forward to file logger to ensure schema stays consistent
        logger.emit(code, d)
        emitted.append({"code": code, **d})

    tracker = AckTracker(events_emit=_capture, ttl_s=0)
    tracker.add_submit(symbol="ETHUSDT", cid="C3", side="BUY", qty=1.0, t_submit_ns=1)
    # immediate scan should expire since ttl=0
    n = tracker.scan_once(now_ns=2)
    assert n == 1

    rows = read_jsonl(p)
    codes = [r["event_code"] for r in rows]
    assert "ORDER.CANCEL.REQUEST" in codes
    assert "ORDER.CANCEL.ACK" in codes
    assert "ORDER.EXPIRE" in codes
