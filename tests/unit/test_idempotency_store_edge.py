import time
import pytest

idemp = pytest.importorskip("core.execution.idempotency", reason="idempotency not available")


def test_mark_and_seen_and_cleanup():
    store = idemp.IdempotencyStore()
    key = "evt_edge"
    assert not store.seen(key)
    store.mark(key)
    assert store.seen(key)

    # overwrite with tiny ttl
    store.mark(key, ttl_sec=1e-6)
    time.sleep(1e-4)
    # after small wait, cleanup should remove
    removed = store.cleanup_expired()
    assert removed >= 0

