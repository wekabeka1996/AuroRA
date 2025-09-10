from core.infra.idempotency_store import IdempotencyStore


def test_put_get_seen_and_sweep():
    # deterministic now_ns for testing
    now_ns = lambda: 1_000_000_000
    store = IdempotencyStore(ttl_sec=3600, now_ns_fn=now_ns)
    key = "op-123"
    assert not store.seen(key)
    store.put(key, {"ok": True})
    assert store.seen(key)
    assert store.get(key) == {"ok": True}
    # sweep should remove nothing for large ttl
    removed = store.sweep()
    assert removed == 0


def test_sweep_removes_expired():
    t = [1_000_000_000]
    now_ns = lambda: t[0]
    store = IdempotencyStore(ttl_sec=0.000001, now_ns_fn=now_ns)  # tiny ttl
    store.put("k", 1)
    assert store.seen("k")
    # advance time beyond ttl
    t[0] += int(1e9)
    removed = store.sweep()
    assert removed == 1
    assert not store.seen("k")


def test_put_get_seen_and_sweep():
    # deterministic now_ns for testing
    now_ns = lambda: 1_000_000_000
    store = IdempotencyStore(ttl_sec=3600, now_ns_fn=now_ns)
    key = "op-123"
    assert not store.seen(key)
    store.put(key, {"ok": True})
    assert store.seen(key)
    assert store.get(key) == {"ok": True}
    # sweep should remove nothing for large ttl
    removed = store.sweep()
    assert removed == 0


def test_sweep_removes_expired():
    t = [1_000_000_000]
    now_ns = lambda: t[0]
    store = IdempotencyStore(ttl_sec=0.000001, now_ns_fn=now_ns)  # tiny ttl
    store.put("k", 1)
    assert store.seen("k")
    # advance time beyond ttl
    t[0] += int(1e9)
    removed = store.sweep()
    assert removed == 1
    assert not store.seen("k")
