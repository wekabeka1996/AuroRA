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
from typing import Dict, Optional


class MemoryIdempotencyStore:
    """In-memory idempotency backend with TTL and O(1) ops."""

    def __init__(self) -> None:
        self._store: Dict[str, float] = {}
        self._lock = threading.RLock()

    def seen(self, event_id: str) -> bool:
        with self._lock:
            expiry = self._store.get(event_id)
            if expiry is None:
                return False
            if time.time() > expiry:
                del self._store[event_id]
                return False
            return True

    def mark(self, event_id: str, ttl_sec: float = 300.0) -> None:
        with self._lock:
            self._store[event_id] = time.time() + ttl_sec

    def cleanup_expired(self) -> int:
        with self._lock:
            current_time = time.time()
            expired_keys = [
                k for k, expiry in self._store.items() if current_time > expiry
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
        except Exception as e:
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
