"""
Idempotency Guard layered atop the selected IdempotencyStore.

Key idea:
- For a given client_order_id (COID), we store a JSON payload with fields:
  { "spec_hash": str, "status": str, "updated": int }

Workflow:
- pre_submit_check(coid, spec_hash, ttl) -> one of:
    - returns cached dict when existing and matches spec_hash (duplicate)
    - raises ValueError on conflict when spec_hash mismatches (same COID, different spec)
    - returns None when not found (fresh submit allowed)
- mark_status(coid, status, ttl) -> upserts status with given ttl, preserving spec_hash when present

Statuses are free-form strings but recommended values are: PENDING, ACK, PARTIAL, FILLED, CANCELED, REJECTED, ERROR.
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, Mapping, Optional

from core.aurora_event_logger import AuroraEventLogger
from observability.codes import (
    IDEM_CONFLICT,
    IDEM_DUP,
    IDEM_HIT,
    IDEM_STORE,
    IDEM_UPDATE,
)

from .idempotency import IdempotencyStore

# Singleton store instance to ensure in-memory backend observes prior writes
_STORE = IdempotencyStore()
_LOGGER: AuroraEventLogger | None = None
_METRICS: Any | None = None  # expects api.sli_metrics.IdemMetrics-like interface


class IdempotencyConflict(RuntimeError):
    """Raised when the same client_order_id is reused with a different spec.

    Meant to be mapped to HTTP 409 semantics at the API layer.
    """

    pass


def set_event_logger(logger: AuroraEventLogger | None) -> None:
    global _LOGGER
    _LOGGER = logger


def set_idem_metrics(metrics: Any | None) -> None:
    global _METRICS
    _METRICS = metrics


def _loads_safe(raw: Optional[str]) -> Optional[Dict[str, Any]]:
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def pre_submit_check(
    coid: str, spec_hash: str, ttl_sec: float = 600.0
) -> Optional[Dict[str, Any]]:
    """Check if a given client order id has been seen.

    - If stored payload exists and spec_hash matches -> return payload (duplicate OK)
    - If stored payload exists and spec_hash differs -> raise ValueError (conflict)
    - If not found -> prime the store with PENDING status and return None
    """
    store = _STORE
    raw = store.get(coid) if hasattr(store, "get") else None
    payload = _loads_safe(raw)
    if payload is not None:
        existing_hash = payload.get("spec_hash")
        if existing_hash and existing_hash != spec_hash:
            # emit conflict
            try:
                if _LOGGER:
                    _LOGGER.emit(IDEM_CONFLICT, {"cid": coid})
            except Exception:
                pass
            try:
                if _METRICS:
                    _METRICS.inc_check("conflict")
            except Exception:
                pass
            raise IdempotencyConflict(
                "IDEMPOTENCY_CONFLICT: same client_order_id with different spec"
            )
        # duplicate hit
        try:
            if _LOGGER:
                _LOGGER.emit(IDEM_HIT, {"cid": coid})
                _LOGGER.emit(IDEM_DUP, {"cid": coid})
        except Exception:
            pass
        try:
            if _METRICS:
                _METRICS.inc_check("hit")
                _METRICS.inc_dup_submit()
        except Exception:
            pass
        return payload

    # not found -> mark PENDING now
    data = {"spec_hash": spec_hash, "status": "PENDING", "updated": int(time.time())}
    if hasattr(store, "put"):
        store.put(coid, json.dumps(data), ttl_sec)
    else:
        # fallback minimal marker
        store.mark(coid, ttl_sec)
    # emit store
    try:
        if _LOGGER:
            _LOGGER.emit(IDEM_STORE, {"cid": coid})
    except Exception:
        pass
    try:
        if _METRICS:
            _METRICS.inc_check("store")
    except Exception:
        pass
    return None


def mark_status(
    coid: str,
    new_status: str,
    ttl_sec: float = 3600.0,
    *,
    result: Optional[Mapping[str, object]] = None,
) -> Dict[str, Any]:
    """Update status for COID and extend ttl. Preserves spec_hash if recorded earlier.

    Optionally caches last known order result under key 'result' for duplicate HITs.
    """
    store = _STORE
    prev = _loads_safe(store.get(coid) if hasattr(store, "get") else None) or {}
    payload = {
        "spec_hash": prev.get("spec_hash"),
        "status": new_status,
        "updated": int(time.time()),
    }
    if result is not None:
        try:
            payload["result"] = dict(result)
        except Exception:
            # best-effort, ignore non-mapping types
            pass
    if hasattr(store, "put"):
        # Use default=str to handle Decimal and non-JSON-native types in cached result
        store.put(coid, json.dumps(payload, default=str), ttl_sec)
    else:
        store.mark(coid, ttl_sec)
    # emit update
    try:
        if _LOGGER:
            _LOGGER.emit(IDEM_UPDATE, {"cid": coid, "status": new_status})
    except Exception:
        pass
    try:
        if _METRICS:
            _METRICS.inc_update(str(new_status))
    except Exception:
        pass
    return payload


__all__ = [
    "pre_submit_check",
    "mark_status",
    "set_event_logger",
    "set_idem_metrics",
    "IdempotencyConflict",
]
