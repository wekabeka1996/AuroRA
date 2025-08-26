from __future__ import annotations

import json
import time
from collections import deque
from pathlib import Path
from typing import Any, Dict, Optional, Deque, Tuple

# Reuse robust JSONL writer and small LRU from order logger
from core.order_logger import _JsonlWriter, _LRUSet  # type: ignore
import os


class AuroraEventLogger:
    # Allowed event codes
    ALLOWED = {
        # Rewards
        "REWARD.TP", "REWARD.TRAIL", "REWARD.BREAKEVEN", "REWARD.TIMEOUT", "REWARD.MAX_R",
        # Health
    "HEALTH.ERROR", "HEALTH.RECOVERY", "HEALTH.LATENCY_HIGH", "HEALTH.LATENCY_P95_HIGH",
        # Lifecycle/ops
    "AURORA.STARTUP.OK", "CONFIG.SWITCHED", "AURORA.ESCALATION",
    "OPS.TOKEN_ROTATE", "OPS.RESET", "AURORA.COOL_OFF", "AURORA.ARM_STATE",
    "OPS.TOKEN.ALIAS_USED",
    # Order lifecycle
        "ORDER.SUBMIT", "ORDER.ACK", "ORDER.PARTIAL", "ORDER.FILL",
        "ORDER.CANCEL", "ORDER.CANCEL.REQUEST", "ORDER.CANCEL.ACK",
        "ORDER.REJECT", "ORDER.EXPIRE",
        # Risk
    "RISK.DENY.POS_LIMIT", "RISK.DENY.DRAWDOWN", "RISK.DENY.CVAR", "RISK.DENY",
    "RISK.UPDATE",
        # Guards
    "SPREAD_GUARD_TRIP", "LATENCY_GUARD_TRIP", "VOLATILITY_GUARD_TRIP",
    # Policy
    "POLICY.TRAP_GUARD", "POLICY.TRAP_BLOCK", "POLICY.DECISION",
    # Post-trade
    "POSTTRADE.LOG",
        # Data quality
        "DQ_EVENT.STALE_BOOK", "DQ_EVENT.CROSSED_BOOK", "DQ_EVENT.ABNORMAL_SPREAD", "DQ_EVENT.CYCLIC_SEQUENCE",
        # Halt
        "AURORA.HALT", "AURORA.RESUME",
    # Expected return + slippage guards
    "AURORA.EXPECTED_RETURN_ACCEPT", "AURORA.EXPECTED_RETURN_LOW", "AURORA.SLIPPAGE_GUARD",
    }

    def __init__(
        self,
        path: str | Path | None = None,
        max_bytes: int = 200 * 1024 * 1024,
        retention_days: int = 7,
    ) -> None:
        # Default to session directory if provided via env, else fallback to logs/
        if path is None:
            base = Path(os.getenv("AURORA_SESSION_DIR", "logs"))
            self.path = base / "aurora_events.jsonl"
        else:
            # If caller passed a path explicitly, honor it as-is
            self.path = Path(path)
        self._writer = _JsonlWriter(self.path, max_bytes=max_bytes, retention_days=retention_days)
        self._last_health_emit_ts: Dict[str, float] = {}
        self._seen: _LRUSet = _LRUSet(32768)
        self._run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime())
        # Optional Prometheus Counter hook: set via set_counter()
        self._prom_counter = None
        # Monotonic guard for generated ts_ns to avoid duplicates when clock resolution is coarse
        self._last_emit_ns: int = 0

    @staticmethod
    def _canon_code(code: str) -> str:
        # Normalize only ORDER_* legacy underscore form like ORDER_SUBMIT -> ORDER.SUBMIT.
        # Keep other codes as-is to preserve canonical spelling (e.g., SPREAD_GUARD_TRIP, REWARD.MAX_R).
        raw = (code or "").strip().upper()
        if raw.startswith("ORDER_") and "." not in raw:
            return raw.replace("_", ".")
        return raw

    def emit(
        self,
        event_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
        position_id: Optional[str] = None,
        src: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        """Emit an event record.

        Supports two signatures:
        1) New: emit(event_code: str, details: dict, position_id?: str, src?: str)
        2) Legacy: emit(type: str, payload: dict, severity?: str, code?: str)
           In legacy form, if 'code' is provided it will be used as event_code;
           otherwise, 'type' will be used.
        """
        # Back-compat mapping for legacy kwargs signature used by api/service.py
        if (event_code is None or details is None) and ("type" in kwargs or "payload" in kwargs or "code" in kwargs):
            legacy_type = kwargs.get("type")
            legacy_code = kwargs.get("code")
            payload = kwargs.get("payload")
            # Prefer explicit 'code' when provided, otherwise fallback to 'type'
            event_code = legacy_code or legacy_type
            if not isinstance(payload, dict):
                payload = {"payload": payload}
            details = payload

        if event_code is None:
            raise ValueError("event_code is required")

        ec = self._canon_code(str(event_code))
        if ec not in self.ALLOWED:
            raise ValueError(f"Unknown event_code: {event_code}")
        # Debounce health events (<= 10 Hz per code)
        if ec.startswith("HEALTH."):
            now = time.time()
            last = self._last_health_emit_ts.get(ec, 0.0)
            if now - last < 0.1:
                return
            self._last_health_emit_ts[ec] = now

        d = dict(details or {})
        ts_ns = d.pop("ts_ns", None)
        if ts_ns is None:
            ts_ns = int(time.time() * 1_000_000_000)
        try:
            ts_ns = int(ts_ns)
        except Exception:
            ts_ns = int(time.time() * 1_000_000_000)
        # Ensure strictly increasing to avoid idempotency collisions within same clock tick
        if ts_ns <= self._last_emit_ns:
            ts_ns = self._last_emit_ns + 1
        self._last_emit_ns = ts_ns
        record = {
            "ts_ns": ts_ns,
            "run_id": self._run_id,
            "event_code": ec,
            "symbol": d.pop("symbol", None),
            "cid": d.pop("cid", None),
            "oid": d.pop("oid", None),
            "side": d.pop("side", None),
            "order_type": d.pop("order_type", None),
            "price": d.pop("price", None),
            "qty": d.pop("qty", None),
            "position_id": position_id or d.pop("position_id", None),
            "details": d or {},
            "src": src or d.pop("src", None),
        }
        # Idempotency: (event_code, cid, oid, ts_ns)
        key = (record["event_code"], record.get("cid"), record.get("oid"), record["ts_ns"])  # type: ignore[index]
        if self._seen.contains(key):
            return
        self._seen.add(key)
        try:
            self._writer.write_line(json.dumps(record, ensure_ascii=False))
            # Optional metrics hook
            try:
                pc = getattr(self, "_prom_counter", None)
                if pc is not None:
                    pc.labels(code=ec).inc()
            except Exception:
                # Never fail emit due to metrics issues
                pass
        except Exception:
            pass

    # --- Optional Prometheus hook configuration ---
    def set_counter(self, counter: object) -> None:
        """Attach a Prometheus Counter vector (with label 'code') for increments after successful writes.

        counter must support: counter.labels(code=str).inc()
        """
        self._prom_counter = counter
