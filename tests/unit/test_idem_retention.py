"""
Unit tests for retention-only cleanup in SQLiteIdempotencyStore.
Ensures reads do not delete expired keys and cleanup honors retention window.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from core.execution._idem_store_sqlite import SQLiteIdempotencyStore


def _tmp_db_path(tmp_path: Path) -> str:
    return tmp_path.joinpath("idem_test.db").as_posix()


def test_expired_not_deleted_on_read(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    # Very short TTL to expire quickly
    db_path = _tmp_db_path(tmp_path)
    store = SQLiteIdempotencyStore(db_path=db_path)
    try:
        store.mark("k1", ttl_sec=0.05)
        time.sleep(0.08)
        # Expired -> seen() should be False, but entry should still be present until cleanup
        assert store.seen("k1") is False
        # get() should return None (expired) but not delete; size remains 1
        assert store.get("k1") is None
        assert store.size() == 1
    finally:
        store.close()


def test_cleanup_respects_retention_window(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    db_path = _tmp_db_path(tmp_path)
    store = SQLiteIdempotencyStore(db_path=db_path)
    try:
        # Set retention to 0 days to allow immediate deletion of expired rows on cleanup
        monkeypatch.setenv("AURORA_IDEM_RETENTION_DAYS", "0")
        store.mark("k_old", ttl_sec=0.01)
        time.sleep(0.02)  # ensure expired
        before = store.size()
        assert before == 1
        removed = store.cleanup_expired()
        # With 0-day retention, expired entry should be deleted
        assert removed >= 1
        assert store.size() == 0

        # Now set retention to a large window; expired but within retention should not be deleted
        store.mark("k_recent", ttl_sec=0.01)
        time.sleep(0.02)
        monkeypatch.setenv("AURORA_IDEM_RETENTION_DAYS", "365")
        removed2 = store.cleanup_expired()
        # Should not remove because expiry is not older than cutoff_ns (now - retention)
        assert removed2 == 0
        assert store.size() == 1
    finally:
        store.close()
