from __future__ import annotations

"""
Execution — Idempotency Store
============================

Thread-safe idempotency store facade with pluggable backends (memory|sqlite).

Default backend is in-memory. To enable persistence, set env AURORA_IDEM_BACKEND=sqlite
and optionally AURORA_IDEM_SQLITE_PATH (default: data/idem.db).
"""

import os
import threading
import time
from typing import Dict, Optional, Tuple


class MemoryIdempotencyStore:
    """In-memory idempotency backend with TTL and O(1) ops."""

    def __init__(self) -> None:
        # key -> (expiry_epoch_sec, value_str_or_none)
        self._store: Dict[str, Tuple[float, Optional[str]]] = {}
        self._lock = threading.RLock()

    def seen(self, event_id: str) -> bool:
        with self._lock:
            entry = self._store.get(event_id)
            if entry is None:
                return False
            expiry, _ = entry
            if time.time() > expiry:
                self._store.pop(event_id, None)
                return False
            return True

    def mark(self, event_id: str, ttl_sec: float = 300.0) -> None:
        with self._lock:
            expiry = time.time() + ttl_sec
            value = self._store.get(event_id, (0.0, None))[1]
            self._store[event_id] = (expiry, value)

    # Optional value API (mirrors SQLite backend)
    def put(self, key: str, value: str, ttl_sec: Optional[float] = None) -> None:
        with self._lock:
            now = time.time()
            if ttl_sec is None:
                # preserve existing expiry if present; otherwise default 5 minutes
                expiry = self._store.get(key, (now + 300.0, None))[0]
            else:
                expiry = now + float(ttl_sec)
            self._store[key] = (expiry, value)

    def get(self, key: str) -> Optional[str]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            expiry, value = entry
            if time.time() > expiry:
                self._store.pop(key, None)
                return None
            return value

    def cleanup_expired(self) -> int:
        with self._lock:
            current_time = time.time()
            expired_keys = [
                k for k, (expiry, _v) in self._store.items() if current_time > expiry
            ]
            for key in expired_keys:
                del self._store[key]
            return len(expired_keys)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        with self._lock:
            return len(self._store)


def _select_backend():
    backend = (os.getenv("AURORA_IDEM_BACKEND") or "memory").strip().lower()
    if backend == "sqlite":
        try:
            from ._idem_store_sqlite import SQLiteIdempotencyStore  # type: ignore
        except Exception:
            # Fallback to memory if SQLite backend is not available
            return MemoryIdempotencyStore

        db_path = os.getenv("AURORA_IDEM_SQLITE_PATH") or "data/idem.db"

        class _Bound(SQLiteIdempotencyStore):  # type: ignore
            def __init__(self):
                super().__init__(db_path=db_path)

        return _Bound
    else:
        return MemoryIdempotencyStore


# Public alias: IdempotencyStore points to selected backend class
IdempotencyStore = _select_backend()

__all__ = ["IdempotencyStore", "MemoryIdempotencyStore"]
