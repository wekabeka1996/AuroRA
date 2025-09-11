"""
Unit tests for duplicate event handling with netto-invariance principle.

Tests that 2×ACK, 2×PARTIAL, 2×FILL produce identical results (netto).
Coverage targets: idempotency duplicate event isolation and consistency.
"""

from typing import Any, Dict
from unittest.mock import Mock, call, patch

import pytest

from core.aurora_event_logger import AuroraEventLogger
from core.execution.exchange.common import OrderRequest, OrderResult
from core.execution.idem_guard import IdempotencyConflict, mark_status, pre_submit_check
from core.execution.idempotency import IdempotencyStore, MemoryIdempotencyStore


class TestDuplicateEventsNoppoNetto:
    """Test duplicate event handling maintains netto-invariance principle."""

    def setup_method(self):
        """Setup test environment with fresh memory store."""
        self.store = MemoryIdempotencyStore()
        self.mock_event_logger = Mock(spec=AuroraEventLogger)

        # Base order request for consistent testing
        self.base_request = OrderRequest(
            symbol="SOLUSDT",
            side="BUY",
            type="LIMIT",
            quantity=10.0,
            price=150.0,
            timeInForce="GTC",
            reduceOnly=False,
            workingType="CONTRACT_PRICE",
        )

        # Order results for different event types
        self.ack_result = OrderResult(
            status="NEW",
            orderId=12345,
            clientOrderId="test_client_id",
            price=150.0,
            quantity=10.0,
            executedQty=0.0,
            cummulativeQuoteQty=0.0,
            timeInForce="GTC",
            type="LIMIT",
            side="BUY",
            fills=[],
            workingTime=1694419200000,
            selfTradePreventionMode="NONE",
        )

        self.partial_result = OrderResult(
            status="PARTIALLY_FILLED",
            orderId=12345,
            clientOrderId="test_client_id",
            price=150.0,
            quantity=10.0,
            executedQty=6.0,
            cummulativeQuoteQty=900.0,
            timeInForce="GTC",
            type="LIMIT",
            side="BUY",
            fills=[
                {
                    "price": "150.0",
                    "qty": "6.0",
                    "commission": "0.9",
                    "commissionAsset": "USDT",
                    "tradeId": 98765,
                }
            ],
            workingTime=1694419200000,
            selfTradePreventionMode="NONE",
        )

        self.fill_result = OrderResult(
            status="FILLED",
            orderId=12345,
            clientOrderId="test_client_id",
            price=150.0,
            quantity=10.0,
            executedQty=10.0,
            cummulativeQuoteQty=1500.0,
            timeInForce="GTC",
            type="LIMIT",
            side="BUY",
            fills=[
                {
                    "price": "150.0",
                    "qty": "6.0",
                    "commission": "0.9",
                    "commissionAsset": "USDT",
                    "tradeId": 98765,
                },
                {
                    "price": "150.0",
                    "qty": "4.0",
                    "commission": "0.6",
                    "commissionAsset": "USDT",
                    "tradeId": 98766,
                },
            ],
            workingTime=1694419200000,
            selfTradePreventionMode="NONE",
        )

    def _extract_netto_state(self, result: OrderResult) -> Dict[str, Any]:
        """Extract the netto (essential) state from OrderResult for comparison."""
        return {
            "status": result.status,
            "orderId": result.orderId,
            "executedQty": result.executedQty,
            "cummulativeQuoteQty": result.cummulativeQuoteQty,
            "fills_count": len(result.fills) if result.fills else 0,
            "total_commission": sum(
                float(fill.get("commission", 0)) for fill in (result.fills or [])
            ),
        }

    def test_double_ack_events_netto_invariant(self):
        """
        Test that processing 2×ACK events produces identical netto results.

        Principle: Duplicate ACK events should not change the final state.
        """
        request_hash = self._get_request_hash(self.base_request)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # First ACK event
            first_result = store_orderresult(
                self.store,
                request_hash,
                self.ack_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after first ACK
            first_netto = self._extract_netto_state(first_result)

            # Second ACK event (duplicate)
            second_result = store_orderresult(
                self.store,
                request_hash,
                self.ack_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after second ACK
            second_netto = self._extract_netto_state(second_result)

            # CRITICAL: Netto states must be identical
            assert (
                first_netto == second_netto
            ), "Double ACK should produce identical netto state"

            # Verify specific ACK invariants
            assert first_netto["status"] == "NEW"
            assert first_netto["executedQty"] == 0.0
            assert first_netto["cummulativeQuoteQty"] == 0.0
            assert first_netto["fills_count"] == 0

            # Cache retrieval should return consistent result
            cached_result = get_cached_orderresult(
                self.store, request_hash, self.mock_event_logger
            )
            cached_netto = self._extract_netto_state(cached_result)
            assert cached_netto == first_netto, "Cached result should match netto state"

    def test_double_partial_events_netto_invariant(self):
        """
        Test that processing 2×PARTIAL events produces identical netto results.

        Principle: Duplicate PARTIAL events should not accumulate/change execution.
        """
        request_hash = self._get_request_hash(self.base_request)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # First PARTIAL event
            first_result = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after first PARTIAL
            first_netto = self._extract_netto_state(first_result)

            # Second PARTIAL event (duplicate)
            second_result = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after second PARTIAL
            second_netto = self._extract_netto_state(second_result)

            # CRITICAL: Netto states must be identical (no double execution)
            assert (
                first_netto == second_netto
            ), "Double PARTIAL should produce identical netto state"

            # Verify specific PARTIAL invariants
            assert first_netto["status"] == "PARTIALLY_FILLED"
            assert first_netto["executedQty"] == 6.0  # Should NOT be 12.0
            assert first_netto["cummulativeQuoteQty"] == 900.0  # Should NOT be 1800.0
            assert first_netto["fills_count"] == 1  # Should NOT be 2
            assert first_netto["total_commission"] == 0.9  # Should NOT be 1.8

            # Cache consistency check
            cached_result = get_cached_orderresult(
                self.store, request_hash, self.mock_event_logger
            )
            cached_netto = self._extract_netto_state(cached_result)
            assert (
                cached_netto == first_netto
            ), "Cached PARTIAL should match netto state"

    def test_double_fill_events_netto_invariant(self):
        """
        Test that processing 2×FILL events produces identical netto results.

        Principle: Duplicate FILL events should not affect final execution totals.
        """
        request_hash = self._get_request_hash(self.base_request)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # First FILL event
            first_result = store_orderresult(
                self.store,
                request_hash,
                self.fill_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after first FILL
            first_netto = self._extract_netto_state(first_result)

            # Second FILL event (duplicate)
            second_result = store_orderresult(
                self.store,
                request_hash,
                self.fill_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            # Extract netto state after second FILL
            second_netto = self._extract_netto_state(second_result)

            # CRITICAL: Netto states must be identical (no double fills)
            assert (
                first_netto == second_netto
            ), "Double FILL should produce identical netto state"

            # Verify specific FILL invariants
            assert first_netto["status"] == "FILLED"
            assert first_netto["executedQty"] == 10.0  # Should NOT be 20.0
            assert first_netto["cummulativeQuoteQty"] == 1500.0  # Should NOT be 3000.0
            assert first_netto["fills_count"] == 2  # Should NOT be 4
            assert first_netto["total_commission"] == 1.5  # Should NOT be 3.0

            # Cache consistency check
            cached_result = get_cached_orderresult(
                self.store, request_hash, self.mock_event_logger
            )
            cached_netto = self._extract_netto_state(cached_result)
            assert cached_netto == first_netto, "Cached FILL should match netto state"

    def test_mixed_duplicate_events_sequence_netto_invariant(self):
        """
        Test complex sequence: ACK → ACK → PARTIAL → PARTIAL → FILL → FILL.

        Principle: Each duplicate should be noop, final state should match single sequence.
        """
        request_hash = self._get_request_hash(self.base_request)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # Single sequence: ACK → PARTIAL → FILL
            single_store = MemoryIdempotencyStore()

            single_ack = store_orderresult(
                single_store,
                request_hash,
                self.ack_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )
            single_partial = store_orderresult(
                single_store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )
            single_fill = store_orderresult(
                single_store,
                request_hash,
                self.fill_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            single_final_netto = self._extract_netto_state(single_fill)

            # Duplicate sequence: ACK → ACK → PARTIAL → PARTIAL → FILL → FILL
            dup_ack1 = store_orderresult(
                self.store,
                request_hash,
                self.ack_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )
            dup_ack2 = store_orderresult(
                self.store,
                request_hash,
                self.ack_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            dup_partial1 = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )
            dup_partial2 = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            dup_fill1 = store_orderresult(
                self.store,
                request_hash,
                self.fill_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )
            dup_fill2 = store_orderresult(
                self.store,
                request_hash,
                self.fill_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            dup_final_netto = self._extract_netto_state(dup_fill2)

            # CRITICAL: Both sequences must produce identical netto results
            assert (
                single_final_netto == dup_final_netto
            ), "Single vs duplicate sequence should produce identical netto"

            # Verify final state invariants
            assert dup_final_netto["status"] == "FILLED"
            assert dup_final_netto["executedQty"] == 10.0
            assert dup_final_netto["cummulativeQuoteQty"] == 1500.0
            assert dup_final_netto["fills_count"] == 2
            assert dup_final_netto["total_commission"] == 1.5

    def test_duplicate_events_with_idempotency_guard_netto_consistency(self):
        """
        Test duplicate event handling through IdempotencyGuard maintains netto consistency.

        Principle: Guard should prevent duplicate processing at the highest level.
        """
        guard = IdempotencyGuard(self.store, ttl_sec=3600.0)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # Mock HTTP client that should only be called once per unique request
            mock_http_client = Mock()
            mock_http_client.place_order.return_value = self.ack_result

            # First call - should hit HTTP client
            first_result = guard.get_or_execute(
                self.base_request,
                lambda req: mock_http_client.place_order(req),
                self.mock_event_logger,
            )

            # Second call (duplicate) - should hit cache, not HTTP client
            second_result = guard.get_or_execute(
                self.base_request,
                lambda req: mock_http_client.place_order(req),
                self.mock_event_logger,
            )

            # Extract netto states
            first_netto = self._extract_netto_state(first_result)
            second_netto = self._extract_netto_state(second_result)

            # CRITICAL: Netto states must be identical
            assert (
                first_netto == second_netto
            ), "Guard duplicate handling should maintain netto consistency"

            # HTTP client should be called exactly once
            assert (
                mock_http_client.place_order.call_count == 1
            ), "HTTP client should be called only once for duplicates"

            # Both results should be the same object reference (cache hit)
            assert (
                first_result is second_result
            ), "Cached result should be same object reference"

    def test_rapid_duplicate_events_netto_stability(self):
        """
        Test rapid duplicate event processing maintains netto stability.

        Principle: High-frequency duplicates should not create race conditions.
        """
        import threading
        import time

        request_hash = self._get_request_hash(self.base_request)
        results = []
        errors = []

        def rapid_store_events():
            """Rapidly store duplicate events."""
            try:
                for i in range(10):
                    result = store_orderresult(
                        self.store,
                        request_hash,
                        self.fill_result,
                        self.mock_event_logger,
                        ttl_sec=3600.0,
                    )
                    results.append(result)
                    time.sleep(0.001)  # Small delay to simulate processing time
            except Exception as e:
                errors.append(e)

        # Start multiple threads doing rapid duplicate processing
        threads = []
        for _ in range(3):
            thread = threading.Thread(target=rapid_store_events)
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=5.0)

        # Should have no errors
        assert (
            len(errors) == 0
        ), f"Rapid duplicate processing should not cause errors: {errors}"

        # Should have results from all threads
        assert (
            len(results) == 30
        ), "Should have results from all rapid duplicate attempts"

        # All results should have identical netto state
        netto_states = [self._extract_netto_state(result) for result in results]
        first_netto = netto_states[0]

        for i, netto in enumerate(netto_states[1:], 1):
            assert (
                netto == first_netto
            ), f"Result {i} should have identical netto state to first result"

        # Verify final cache state is consistent
        cached_result = get_cached_orderresult(
            self.store, request_hash, self.mock_event_logger
        )
        cached_netto = self._extract_netto_state(cached_result)
        assert (
            cached_netto == first_netto
        ), "Final cached state should match netto invariant"

    def test_duplicate_detection_does_not_affect_netto_computation(self):
        """
        Test that duplicate detection logic does not interfere with netto computation.

        Principle: Detection is orthogonal to state computation.
        """
        request_hash = self._get_request_hash(self.base_request)

        with patch.object(self.mock_event_logger, "log_event") as mock_log:
            # Store initial result
            initial_result = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            initial_netto = self._extract_netto_state(initial_result)

            # Store duplicate - should trigger duplicate detection
            duplicate_result = store_orderresult(
                self.store,
                request_hash,
                self.partial_result,
                self.mock_event_logger,
                ttl_sec=3600.0,
            )

            duplicate_netto = self._extract_netto_state(duplicate_result)

            # CRITICAL: Netto computation should be unaffected by duplicate detection
            assert (
                initial_netto == duplicate_netto
            ), "Duplicate detection should not affect netto computation"

            # Verify the state values are still correct
            assert duplicate_netto["status"] == "PARTIALLY_FILLED"
            assert duplicate_netto["executedQty"] == 6.0
            assert duplicate_netto["cummulativeQuoteQty"] == 900.0
            assert duplicate_netto["fills_count"] == 1

            # The objects should be identical (cache hit behavior)
            assert (
                initial_result is duplicate_result
            ), "Duplicate should return same object reference"

    def _get_request_hash(self, request: OrderRequest) -> str:
        """Generate consistent hash for OrderRequest."""
        from core.execution.idempotency import _hash_order_request

        return _hash_order_request(request)
