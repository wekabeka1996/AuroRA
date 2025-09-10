from core.infra.idempotency_store import IdempotencyStore


def test_idempotency_ttl_and_overwrite(tmp_path):
    # Test TTL expiration and key overwrite
    now_ns = [1_000_000_000]
    store = IdempotencyStore(ttl_sec=0.001, now_ns_fn=lambda: now_ns[0])  # Very short TTL

    # Put and check
    store.put("key1", "val1")
    assert store.seen("key1")
    assert store.get("key1") == "val1"

    # Overwrite
    store.put("key1", "val2")
    assert store.get("key1") == "val2"

    # Advance time beyond TTL
    now_ns[0] += int(1e9)  # 1 second later
    store.sweep()
    assert not store.seen("key1")
    assert store.get("key1") is None
