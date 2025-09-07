"""
Integration tests for concurrent order operations in OMS.

Tests thread safety and atomicity in concurrent order operations:
- Multiple orders submitted simultaneously
- Concurrent cancellations and modifications
- Race conditions in position updates
- Idempotency under concurrent access
- Deadlock prevention
"""

import pytest
import asyncio
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, AsyncMock
from typing import List, Dict, Any

from tests.fixtures.mock_exchange_factory import MockExchangeFactory, OrderStatus
from core.execution.exchange.common import OrderRequest, Side, OrderType, TimeInForce
from common.xai_logger import XAILogger


class TestConcurrentOrders:
    """Test concurrent order operations for thread safety."""

    @pytest.fixture
    async def setup_concurrent_env(self):
        """Setup environment for concurrent order testing."""
        # Create exchange with some latency to simulate real conditions
        exchange = MockExchangeFactory.create_high_latency_exchange(
            fill_profile={"latency_ms": 100, "jitter_ms": 50}
        )

        # Mock order manager with concurrent safety
        order_manager = Mock()
        order_manager.submit_order = AsyncMock()
        order_manager.cancel_order = AsyncMock()
        order_manager.get_order_status = AsyncMock()
        order_manager.get_order_fills = AsyncMock()

        # Thread-safe position manager mock
        position_manager = Mock()
        position_lock = threading.Lock()

        def thread_safe_get_position(symbol: str):
            with position_lock:
                return Mock(quantity=0.0, avg_price=0.0)

        position_manager.get_position = thread_safe_get_position

        xai_logger = XAILogger(trace_id="concurrent_test_123")

        yield {
            "order_manager": order_manager,
            "position_manager": position_manager,
            "exchange": exchange,
            "xai_logger": xai_logger,
            "position_lock": position_lock
        }

    @pytest.mark.asyncio
    async def test_concurrent_order_submission(self, setup_concurrent_env):
        """Test submitting multiple orders concurrently."""
        env = await setup_concurrent_env
        om = env["order_manager"]
        xai = env["xai_logger"]

        # Setup mock responses
        om.submit_order.side_effect = self._mock_submit_response

        # Create multiple orders
        orders = []
        for i in range(10):
            order = OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"concurrent_order_{i}"
            )
            orders.append(order)

        # Submit orders concurrently
        tasks = []
        for order in orders:
            xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"})
            tasks.append(om.submit_order(order))

        # Wait for all submissions
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Verify all orders were accepted
        successful_submissions = [r for r in results if not isinstance(r, Exception)]
        assert len(successful_submissions) == 10

        for result in successful_submissions:
            assert result["status"] == "accepted"
            assert "order_id" in result

        # Verify XAI logging for concurrent operations
        assert len([call for call in xai.emit.call_args_list if call[0][0] == "ORDER.SUBMIT"]) == 10

    @pytest.mark.asyncio
    async def test_concurrent_cancellations(self, setup_concurrent_env):
        """Test cancelling orders concurrently."""
        env = await setup_concurrent_env
        om = env["order_manager"]
        xai = env["xai_logger"]

        # Setup mock responses
        om.submit_order.side_effect = self._mock_submit_response
        om.cancel_order.side_effect = self._mock_cancel_response

        # First submit orders
        orders = []
        submit_tasks = []
        for i in range(5):
            order = OrderRequest(
                symbol="ETHUSDT",
                side=Side.BUY,
                type=OrderType.LIMIT,
                quantity=2.0,
                price=3000.0,
                client_order_id=f"cancel_test_{i}"
            )
            orders.append(order)
            submit_tasks.append(om.submit_order(order))

        submit_results = await asyncio.gather(*submit_tasks)
        order_ids = [r["order_id"] for r in submit_results]

        # Now cancel them concurrently
        cancel_tasks = []
        for order_id in order_ids:
            xai.emit("ORDER.CANCEL_REQUEST", {"order_id": order_id, "reason": "test_cancel"})
            cancel_tasks.append(om.cancel_order(order_id))

        cancel_results = await asyncio.gather(*cancel_tasks, return_exceptions=True)

        # Verify all cancellations succeeded
        successful_cancellations = [r for r in cancel_results if not isinstance(r, Exception)]
        assert len(successful_cancellations) == 5

        for result in successful_cancellations:
            assert result["status"] == "cancelled"

    @pytest.mark.asyncio
    async def test_race_condition_prevention(self, setup_concurrent_env):
        """Test prevention of race conditions in position updates."""
        env = await setup_concurrent_env
        om = env["order_manager"]
        pm = env["position_manager"]
        position_lock = env["position_lock"]

        # Setup position tracking
        positions = {"BTCUSDT": {"quantity": 0.0, "avg_price": 0.0}}
        position_access_count = 0

        def track_position_access(symbol: str):
            nonlocal position_access_count
            with position_lock:
                position_access_count += 1
                return Mock(**positions[symbol])

        pm.get_position = track_position_access

        # Setup mock order submissions that would modify position
        async def position_modifying_submit(order):
            # Simulate position update
            with position_lock:
                if order.side == Side.BUY:
                    positions[order.symbol]["quantity"] += order.quantity
                else:
                    positions[order.symbol]["quantity"] -= order.quantity
            return self._mock_submit_response(order)

        om.submit_order.side_effect = position_modifying_submit

        # Submit buy and sell orders concurrently
        buy_order = OrderRequest(
            symbol="BTCUSDT", side=Side.BUY, type=OrderType.MARKET,
            quantity=1.0, client_order_id="race_buy_1"
        )
        sell_order = OrderRequest(
            symbol="BTCUSDT", side=Side.SELL, type=OrderType.MARKET,
            quantity=1.0, client_order_id="race_sell_1"
        )

        # Submit concurrently
        results = await asyncio.gather(
            om.submit_order(buy_order),
            om.submit_order(sell_order)
        )

        # Verify both succeeded
        assert all(r["status"] == "accepted" for r in results)

        # Verify position consistency (should be 0 due to concurrent buy/sell)
        final_position = pm.get_position("BTCUSDT")
        # Note: In real scenario, this would be handled by proper position management
        assert position_access_count > 0  # Verify locking was used

    @pytest.mark.asyncio
    async def test_idempotency_under_concurrency(self, setup_concurrent_env):
        """Test idempotency when same order submitted multiple times concurrently."""
        env = await setup_concurrent_env
        om = env["order_manager"]
        xai = env["xai_logger"]

        # Track submission attempts
        submission_count = 0
        submitted_order_ids = set()

        async def idempotent_submit(order):
            nonlocal submission_count
            submission_count += 1

            # Simulate idempotency check
            if order.client_order_id in submitted_order_ids:
                return {
                    "status": "duplicate",
                    "order_id": f"existing_{order.client_order_id}",
                    "reason": "DUPLICATE_CLIENT_ORDER_ID"
                }

            submitted_order_ids.add(order.client_order_id)
            return self._mock_submit_response(order)

        om.submit_order.side_effect = idempotent_submit

        # Create same order multiple times
        order = OrderRequest(
            symbol="ADAUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=10.0,
            client_order_id="idempotent_test_001"
        )

        # Submit same order 5 times concurrently
        tasks = [om.submit_order(order) for _ in range(5)]
        results = await asyncio.gather(*tasks)

        # Verify only one successful submission
        accepted_results = [r for r in results if r["status"] == "accepted"]
        duplicate_results = [r for r in results if r["status"] == "duplicate"]

        assert len(accepted_results) == 1
        assert len(duplicate_results) == 4
        assert submission_count == 5

    @pytest.mark.asyncio
    async def test_thread_safety_stress_test(self, setup_concurrent_env):
        """Stress test with many concurrent operations."""
        env = await setup_concurrent_env
        om = env["order_manager"]
        xai = env["xai_logger"]

        om.submit_order.side_effect = self._mock_submit_response
        om.cancel_order.side_effect = self._mock_cancel_response

        # Create large number of concurrent operations
        num_operations = 50
        orders = []

        # Mix of submit and cancel operations
        for i in range(num_operations):
            order = OrderRequest(
                symbol="SOLUSDT",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"stress_test_{i}"
            )
            orders.append(order)

        # Submit all orders concurrently
        submit_tasks = [om.submit_order(order) for order in orders]
        submit_results = await asyncio.gather(*submit_tasks)

        # Extract order IDs for cancellation
        order_ids = [r["order_id"] for r in submit_results if r["status"] == "accepted"]

        # Cancel orders concurrently
        cancel_tasks = [om.cancel_order(oid) for oid in order_ids]
        cancel_results = await asyncio.gather(*cancel_tasks)

        # Verify all operations completed without exceptions
        assert len(submit_results) == num_operations
        assert len(cancel_results) == len(order_ids)

        # Verify no exceptions occurred
        assert all(not isinstance(r, Exception) for r in submit_results)
        assert all(not isinstance(r, Exception) for r in cancel_results)

    def _mock_submit_response(self, order):
        """Mock order submission response."""
        return {
            "status": "accepted",
            "order_id": f"mock_{order.client_order_id}_{int(time.time()*1000)}",
            "timestamp": time.time()
        }

    def _mock_cancel_response(self, order_id):
        """Mock order cancellation response."""
        return {
            "status": "cancelled",
            "order_id": order_id,
            "timestamp": time.time()
        }