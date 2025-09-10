from __future__ import annotations

"""
Execution — Idempotency Store
============================

Thread-safe idempotency store for order lifecycle management. Prevents duplicate
order submissions and tracks order states across retries and failures.

Key features:
- O(1) lookups for event deduplication
- TTL-based cleanup for memory efficiency
- Thread-safe operations
- Support for order_id, fill_id, and order_event_id keys

Integration:
- Used by exchange adapters and order lifecycle manager
- Keys: client_oid, fill_id, order_event_id
"""

import threading
import time


class IdempotencyStore:
    """Thread-safe store for tracking processed events to prevent duplicates.
    
    Example:
        store = IdempotencyStore()
        if not store.seen("order_123"):
            store.mark("order_123", ttl_sec=300)
            # Process order
    """

    def __init__(self) -> None:
        self._store: dict[str, float] = {}
        self._lock = threading.RLock()

    def seen(self, event_id: str) -> bool:
        """Check if event_id has been processed recently."""
        with self._lock:
            expiry = self._store.get(event_id)
            if expiry is None:
                return False

            # Check if expired
            if time.time() > expiry:
                # Clean up expired entry
                del self._store[event_id]
                return False

            return True

    def mark(self, event_id: str, ttl_sec: float = 300.0) -> None:
        """Mark event_id as processed with given TTL in seconds."""
        with self._lock:
            self._store[event_id] = time.time() + ttl_sec

    def cleanup_expired(self) -> int:
        """Remove expired entries. Returns number of entries removed."""
        with self._lock:
            current_time = time.time()
            expired_keys = [k for k, expiry in self._store.items() if current_time > expiry]

            for key in expired_keys:
                del self._store[key]

            return len(expired_keys)

    def clear(self) -> None:
        """Clear all entries (for testing/debugging)."""
        with self._lock:
            self._store.clear()

    def size(self) -> int:
        """Return current number of stored entries."""
        with self._lock:
            return len(self._store)


__all__ = ["IdempotencyStore"]
