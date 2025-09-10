from __future__ import annotations

from pathlib import Path

from core.aurora_event_logger import AuroraEventLogger


def test_invalid_event_code_raises(tmp_path: Path):
    logger = AuroraEventLogger(path=tmp_path / "events.jsonl")
    try:
        logger.emit("NOT.ALLOWED", {"x": 1})
        assert False, "expected ValueError"
    except ValueError:
        pass


essential = [
    "REWARD.TP", "REWARD.TRAIL", "REWARD.BREAKEVEN", "REWARD.TIMEOUT", "REWARD.MAX_R",
    "HEALTH.ERROR", "HEALTH.RECOVERY",
    "AURORA.STARTUP.OK", "CONFIG.SWITCHED",
    # Order lifecycle
    "ORDER.SUBMIT", "ORDER.ACK", "ORDER.PARTIAL", "ORDER.FILL", "ORDER.CANCEL", "ORDER.REJECT", "ORDER.EXPIRE",
    "RISK.DENY.POS_LIMIT", "RISK.DENY.DRAWDOWN", "RISK.DENY.CVAR",
    "SPREAD_GUARD_TRIP", "LATENCY_GUARD_TRIP", "VOLATILITY_GUARD_TRIP",
    "DQ_EVENT.STALE_BOOK", "DQ_EVENT.CROSSED_BOOK", "DQ_EVENT.ABNORMAL_SPREAD", "DQ_EVENT.CYCLIC_SEQUENCE",
]


def test_valid_codes_write(tmp_path: Path):
    p = tmp_path / "events.jsonl"
    logger = AuroraEventLogger(path=p)
    for code in essential:
        logger.emit(code, {"ok": True})
    # health debounce: rapid duplicate should be suppressed
    logger.emit("HEALTH.ERROR", {"e": 1})
    logger.emit("HEALTH.ERROR", {"e": 2})
    text = p.read_text(encoding="utf-8")
    assert len(text.strip().splitlines()) >= len(essential)
