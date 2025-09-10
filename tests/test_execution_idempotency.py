import threading
import time

from core.execution.idempotency import IdempotencyStore


def test_idempotency_store_basic():
    store = IdempotencyStore()

    # Test unseen event
    assert not store.seen("event1")
    assert store.size() == 0

    # Mark as seen
    store.mark("event1", ttl_sec=1.0)
    assert store.seen("event1")
    assert store.size() == 1

    # Test different event
    assert not store.seen("event2")


def test_idempotency_store_ttl():
    store = IdempotencyStore()

    # Mark with short TTL
    store.mark("event1", ttl_sec=0.1)
    assert store.seen("event1")

    # Wait for expiry (longer than TTL)
    time.sleep(0.3)
    assert not store.seen("event1")
    assert store.size() == 0


def test_idempotency_store_cleanup():
    store = IdempotencyStore()

    # Add some entries
    store.mark("event1", ttl_sec=0.1)
    store.mark("event2", ttl_sec=10.0)

    assert store.size() == 2

    # Wait for first to expire
    time.sleep(0.2)

    # Cleanup should remove expired entries
    removed = store.cleanup_expired()
    assert removed == 1
    assert store.size() == 1
    assert not store.seen("event1")
    assert store.seen("event2")


def test_idempotency_store_thread_safety():
    store = IdempotencyStore()
    results = []

    def worker(worker_id: int):
        for i in range(100):
            event_id = f"worker_{worker_id}_event_{i}"
            if not store.seen(event_id):
                store.mark(event_id, ttl_sec=1.0)
                results.append(event_id)

    # Start multiple threads
    threads = []
    for i in range(5):
        t = threading.Thread(target=worker, args=(i,))
        threads.append(t)
        t.start()

    # Wait for completion
    for t in threads:
        t.join()

    # Each event should be processed exactly once
    assert len(results) == 500  # 5 workers * 100 events each
    assert len(set(results)) == 500  # All unique


def test_idempotency_store_clear():
    store = IdempotencyStore()

    store.mark("event1")
    store.mark("event2")
    assert store.size() == 2

    store.clear()
    assert store.size() == 0
    assert not store.seen("event1")
    assert not store.seen("event2")
