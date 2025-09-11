from __future__ import annotations

"""
SQLite-backed Idempotency Store
================================

Thread-safe, durable idempotency key-value store with TTL semantics.

Schema:
  - entries(key TEXT PRIMARY KEY, value TEXT, expiry_ns INTEGER, updated_ns INTEGER)

Primary operations:
    - seen(key): bool — true if exists and not expired
  - mark(key, ttl_sec): upsert with new expiry
  - get/put: optional value payload (TEXT)
    - cleanup_expired: retention sweep (remove rows older than retention window)
  - clear/size: maintenance helpers

Notes:
    - WAL mode for better concurrency (single-process use with threads)
    - Single connection per instance guarded by RLock
    - Nanoseconds clock for consistency with the rest of the codebase
    - Non-destructive reads: get()/seen() will NOT delete expired rows; deletion is performed only
      by cleanup_expired() based on a retention window
"""

import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import Optional


def _ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


class SQLiteIdempotencyStore:
    """SQLite-backed idempotency store with TTL and O(1) lookups (via PRIMARY KEY).

    API mirrors the in-memory IdempotencyStore to allow drop-in replacement.
    """

    def __init__(
        self, db_path: str | os.PathLike[str] = "data/idem.db", now_ns_fn=time.time_ns
    ):
        self._path = Path(db_path)
        _ensure_parent_dir(self._path)
        self._now_ns = now_ns_fn
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(
            self._path.as_posix(), check_same_thread=False, isolation_level=None
        )
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA synchronous=NORMAL;")
        self._init_schema()

    def _init_schema(self) -> None:
        with self._conn:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    expiry_ns INTEGER,
                    updated_ns INTEGER
                );
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_entries_expiry ON entries(expiry_ns);"
            )

    def seen(self, key: str) -> bool:
        now = self._now_ns()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT expiry_ns FROM entries WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            if row is None:
                return False
            expiry_ns = int(row[0]) if row[0] is not None else 0
            if expiry_ns and expiry_ns < now:
                # expired — report not seen, do not delete (retention-only cleanup)
                return False
            return True

    def mark(self, key: str, ttl_sec: float = 300.0) -> None:
        now = self._now_ns()
        expiry_ns = now + int(ttl_sec * 1e9)
        with self._lock, self._conn:
            insert_sql = (
                "INSERT INTO entries(key, value, expiry_ns, updated_ns) "
                "VALUES(?, COALESCE((SELECT value FROM entries WHERE key=?), NULL), ?, ?) "
                "ON CONFLICT(key) DO UPDATE SET "
                "expiry_ns=excluded.expiry_ns, updated_ns=excluded.updated_ns"
            )
            self._conn.execute(insert_sql, (key, key, expiry_ns, now))

    def put(self, key: str, value: str, ttl_sec: Optional[float] = None) -> None:
        now = self._now_ns()
        expiry_ns = None if ttl_sec is None else now + int(ttl_sec * 1e9)
        with self._lock, self._conn:
            insert_sql = (
                "INSERT INTO entries(key, value, expiry_ns, updated_ns) "
                "VALUES(?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "value=excluded.value, expiry_ns=excluded.expiry_ns, "
                "updated_ns=excluded.updated_ns"
            )
            self._conn.execute(insert_sql, (key, value, expiry_ns, now))

    def get(self, key: str) -> Optional[str]:
        now = self._now_ns()
        with self._lock, self._conn:
            cur = self._conn.execute(
                "SELECT value, expiry_ns FROM entries WHERE key = ?", (key,)
            )
            row = cur.fetchone()
            if row is None:
                return None
            value, expiry_ns = row[0], int(row[1]) if row[1] is not None else 0
            if expiry_ns and expiry_ns < now:
                # expired — do not delete on read; return None
                return None
            return value

    def cleanup_expired(self) -> int:
        # Retention-only cleanup: remove rows whose expiry is older than a retention window
        # Env AURORA_IDEM_RETENTION_DAYS controls the window; default 30 days
        days = os.getenv("AURORA_IDEM_RETENTION_DAYS")
        try:
            retention_days = int(days) if days is not None else 30
        except ValueError:
            retention_days = 30
        retention_ns = int(retention_days * 24 * 60 * 60 * 1e9)
        now = self._now_ns()
        cutoff_ns = now - retention_ns
        with self._lock, self._conn:
            # Delete only entries that are expired and whose expiry is older than cutoff
            delete_sql = (
                "DELETE FROM entries WHERE expiry_ns IS NOT NULL "
                "AND expiry_ns < ? AND expiry_ns < ?"
            )
            cur = self._conn.execute(delete_sql, (now, cutoff_ns))
            return cur.rowcount if cur.rowcount is not None else 0

    def clear(self) -> None:
        with self._lock, self._conn:
            self._conn.execute("DELETE FROM entries")

    def size(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(1) FROM entries")
            row = cur.fetchone()
            return int(row[0]) if row and row[0] is not None else 0

    def close(self) -> None:
        with self._lock:
            try:
                self._conn.close()
            except Exception:
                pass


__all__ = ["SQLiteIdempotencyStore"]
