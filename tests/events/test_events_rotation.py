from __future__ import annotations

from pathlib import Path

from core.aurora_event_logger import AuroraEventLogger


def test_events_rotation_smoke(tmp_path: Path):
    p = tmp_path / "aurora_events.jsonl"
    logger = AuroraEventLogger(path=p, max_bytes=128)  # tiny to force rotation
    # write enough events to trigger rotation
    for i in range(200):
        logger.emit("ORDER.SUBMIT", {"symbol": "X", "cid": f"C{i}", "ts_ns": i})
    # current file exists
    assert p.exists()
    # some gz archives should exist
    gz = list(tmp_path.glob("aurora_events.jsonl.*.jsonl.gz"))
    assert len(gz) >= 1
