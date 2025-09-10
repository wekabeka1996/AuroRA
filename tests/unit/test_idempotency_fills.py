"""
Unit Tests — Idempotency for Fills
=================================

Test idempotency handling for order fills and lifecycle events.
Ensures duplicate events don't cause double-counting or invalid state.
"""

from __future__ import annotations

import pytest
import time

from core.execution.idempotency import IdempotencyStore
from core.execution.partials import PartialSlicer


class TestIdempotencyFills:
    """Test idempotency for fills and order events."""
    
    def test_idempotency_store_basic(self):
        """Test basic idempotency store operations."""
        store = IdempotencyStore()
        
        event_id = "order_123"
        
        # Should not be seen initially
        assert not store.seen(event_id)
        
        # Mark as processed
        store.mark(event_id)
        
        # Should be seen now
        assert store.seen(event_id)
        
        # Should expire after TTL
        store.mark(event_id, ttl_sec=0.1)
        time.sleep(0.2)
        assert not store.seen(event_id)
    
    def test_idempotency_store_cleanup(self):
        """Test cleanup of expired entries."""
        store = IdempotencyStore()
        
        # Add some entries
        store.mark("event1", ttl_sec=0.1)
        store.mark("event2", ttl_sec=1.0)
        
        initial_size = store.size()
        assert initial_size >= 2
        
        # Wait for first to expire
        time.sleep(0.2)
        
        # Cleanup expired
        removed = store.cleanup_expired()
        assert removed >= 1
        
        # Check sizes
        assert store.size() < initial_size
    
    def test_fill_idempotency_with_partials(self):
        """Test that duplicate fills don't affect partial fill tracking."""
        slicer = PartialSlicer()
        order_id = "test_order"
        
        # Start order
        slicer.start(order_id, 1.0)
        
        # First fill
        remaining1 = slicer.register_fill(order_id, 0.3)
        assert remaining1 == 0.7
        
        # Duplicate fill should not change state
        remaining2 = slicer.register_fill(order_id, 0.3)
        assert remaining2 == 0.7  # Should remain the same
        
        # New fill should work
        remaining3 = slicer.register_fill(order_id, 0.2)
        assert remaining3 == 0.5
    
    def test_slice_key_determinism(self):
        """Test that slice keys are deterministic for same inputs."""
        slicer = PartialSlicer()
        order_id = "test_order"
        
        slicer.start(order_id, 1.0)
        
        # Get first slice
        slice1 = slicer.next_slice(order_id)
        assert slice1 is not None
        key1 = slice1.key
        
        # Reset and get same slice again
        slicer.start(order_id, 1.0)
        slice2 = slicer.next_slice(order_id)
        assert slice2 is not None
        key2 = slice2.key
        
        # Keys should be identical
        assert key1 == key2
        assert slice1.qty == slice2.qty
    
    def test_idempotency_with_slice_keys(self):
        """Test using slice keys for idempotency."""
        store = IdempotencyStore()
        slicer = PartialSlicer()
        order_id = "test_order"
        
        slicer.start(order_id, 1.0)
        
        # Get slice and use its key for idempotency
        slice_decision = slicer.next_slice(order_id)
        assert slice_decision is not None
        
        slice_key = slice_decision.key
        
        # First time processing this slice
        assert not store.seen(slice_key)
        store.mark(slice_key)
        
        # Duplicate processing should be detected
        assert store.seen(slice_key)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])