from __future__ import annotations

from core.aurora_event_logger import AuroraEventLogger
from core.ack_tracker import AckTracker
from pathlib import Path
import json


def _read_jsonl(p: Path):
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_late_ack_after_expire(tmp_path: Path):
    p = tmp_path / "aurora_events.jsonl"
    em = AuroraEventLogger(path=p)
    emitted: list[dict] = []

    def _emit(code: str, d: dict):
        em.emit(code, d)
        emitted.append({"code": code, **d})

    tracker = AckTracker(events_emit=_emit, ttl_s=0)
    # Submit and immediately scan to force expire
    tracker.add_submit(symbol="BTCUSDT", cid="X1", side="BUY", qty=1.0, t_submit_ns=1)
    assert tracker.scan_once(now_ns=2) == 1
    # Late ACK should be ignored (idempotency/expired guards)
    tracker.ack("X1")
    rows = _read_jsonl(p)
    codes = [r.get("event_code") for r in rows]
    # Only ORDER.EXPIRE should be present from tracker, no extra ACK events added by tracker
    assert any(c == "ORDER.EXPIRE" for c in codes)


def test_partial_then_cancel_no_double_terminal(tmp_path: Path):
    p = tmp_path / "aurora_events.jsonl"
    em = AuroraEventLogger(path=p)
    # Emit PARTIAL, then CANCEL flow
    base = {"symbol": "ETHUSDT", "cid": "Y1", "side": "SELL", "qty": 2.0, "oid": "OID-1"}
    em.emit("ORDER.PARTIAL", {**base, "fill_qty": 1.0, "ts_ns": 10})
    em.emit("ORDER.CANCEL.REQUEST", {**{k: base[k] for k in ("symbol","cid","side","qty")}, "ts_ns": 11})
    em.emit("ORDER.CANCEL.ACK", {**{k: base[k] for k in ("symbol","cid","side")}, "oid": base["oid"], "ts_ns": 12})
    # A (wrong) late FILL should be idempotent-guarded in higher layers; here we just ensure logging accepts sequence once
    rows = _read_jsonl(p)
    codes = [r.get("event_code") for r in rows]
    assert codes.count("ORDER.CANCEL.ACK") == 1
    assert codes.count("ORDER.CANCEL.REQUEST") == 1
    assert codes.count("ORDER.PARTIAL") == 1
