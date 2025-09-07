"""
Mock Exchange Factory for testing order lifecycle scenarios.

Provides configurable exchange mocks with:
- Deterministic vs stochastic fill behavior
- Partial fill profiles
- Latency simulation
- Order rejection patterns
- Price sequences for testing
"""

import asyncio
import random
import time
from decimal import Decimal
from typing import Dict, Any, List, Optional, Union
from enum import Enum
from unittest.mock import Mock, AsyncMock

from core.execution.exchange.common import OrderRequest, Fill, Side, OrderType, TimeInForce


class OrderStatus(str, Enum):
    """Order status enumeration."""
    PENDING = "PENDING"
    OPEN = "OPEN"
    PARTIAL_FILL = "PARTIAL_FILL"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class MockExchange:
    """Mock exchange implementation with configurable behavior."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.orders = {}  # order_id -> order
        self.fills = {}   # order_id -> list of fills
        self.reject_next = None
        self.price_sequence = config.get("price_sequence", [])
        self.price_index = 0

    def set_fill_profile(self, profile: Dict[str, Any]):
        """Update fill profile dynamically."""
        self.config.update(profile)

    def set_reject_next_order(self, reason: str):
        """Set next order to be rejected."""
        self.reject_next = reason

    def reset_reject_pattern(self):
        """Reset rejection pattern."""
        self.reject_next = None

    def trigger_partial_fill(self, order_id: str, quantity: Decimal, price: Decimal):
        """Manually trigger a partial fill for testing."""
        if order_id not in self.fills:
            self.fills[order_id] = []

        fill = Fill(
            price=float(price),
            qty=float(quantity),
            fee=float(quantity * price * Decimal("0.001")),  # 0.1% fee
            fee_asset="USDT",
            ts_ns=int(time.time() * 1_000_000_000)
        )

        self.fills[order_id].append(fill)

    async def submit_order(self, order: OrderRequest) -> Dict[str, Any]:
        """Submit order with configurable behavior."""
        # Check for rejection
        if self.reject_next:
            reason = self.reject_next
            self.reject_next = None
            return {
                "status": "rejected",
                "order_id": f"mock_{order.client_order_id or 'unknown'}",
                "reason": reason,
                "timestamp": time.time()
            }

        # Generate order ID
        order_id = f"mock_{order.client_order_id or 'unknown'}_{int(time.time()*1000)}"
        self.orders[order_id] = order

        # Simulate exchange processing delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Determine fill behavior
        if self.config.get("immediate", True):
            await self._process_fills(order_id, order)
        else:
            # Schedule fills asynchronously
            asyncio.create_task(self._delayed_fill(order_id, order))

        return {
            "status": "accepted",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel order."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        # Simulate cancellation delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Remove from active orders
        del self.orders[order_id]

        return {
            "status": "cancelled",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        order = self.orders[order_id]
        fills = self.fills.get(order_id, [])
        filled_qty = sum(f.qty for f in fills)

        if filled_qty == 0:
            status = "open"
        elif filled_qty < order.quantity:
            status = "partial_fill"
        else:
            status = "filled"

        return {
            "order_id": order_id,
            "status": status,
            "filled_quantity": filled_qty,
            "remaining_quantity": order.quantity - filled_qty,
            "fills": [f.__dict__ for f in fills]
        }

    async def get_order_fills(self, order_id: str) -> List[Fill]:
        """Get fills for order."""
        return self.fills.get(order_id, [])

    async def _process_fills(self, order_id: str, order: OrderRequest):
        """Process fills based on configuration."""
        partial_ratios = self.config.get("partial", [1.0])  # Default full fill

        if order_id not in self.fills:
            self.fills[order_id] = []

        remaining_qty = order.quantity

        for ratio in partial_ratios:
            if remaining_qty <= 0:
                break

            fill_qty = remaining_qty * ratio

            # Get price (from sequence or random)
            if self.price_sequence and self.price_index < len(self.price_sequence):
                price = self.price_sequence[self.price_index]
                self.price_index += 1
            else:
                # Generate realistic price based on order type
                if order.type == OrderType.MARKET:
                    price = 50000 + random.uniform(-1000, 1000)
                else:
                    # Use limit price or generate one
                    price = order.price or 50000

            # Create fill
            fill = Fill(
                price=price,
                qty=fill_qty,
                fee=fill_qty * price * 0.001,  # 0.1% fee
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )

            self.fills[order_id].append(fill)
            remaining_qty -= fill_qty

            # Simulate fill delay between partials
            if len(partial_ratios) > 1:
                await asyncio.sleep(0.05)

    async def _delayed_fill(self, order_id: str, order: OrderRequest):
        """Process delayed fills."""
        # Wait for configured delay
        delay = self.config.get("delay_ms", 100) / 1000
        await asyncio.sleep(delay)

        # Process fills if order still active
        if order_id in self.orders:
            await self._process_fills(order_id, order)


class MockExchangeFactory:
    """Factory for creating mock exchanges with different configurations."""

    @staticmethod
    def create_deterministic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create deterministic exchange for predictable testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [1.0],  # Full fill by default
            "price_sequence": [],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_stochastic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create stochastic exchange with random behavior."""
        config = {
            "immediate": True,
            "latency_ms": random.randint(5, 50),
            "partial": MockExchangeFactory._generate_random_partial_ratios(),
            "price_variation": 0.02,  # 2% price variation
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_slow_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create slow exchange for testing timeouts."""
        config = {
            "immediate": False,
            "latency_ms": 200,
            "delay_ms": 500,
            "partial": [1.0],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_partial_fill_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that does partial fills."""
        config = {
            "immediate": True,
            "latency_ms": 20,
            "partial": [0.3, 0.4, 0.3],  # Multiple partial fills
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_rejecting_exchange(reject_rate: float = 0.1, fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that randomly rejects orders."""
        config = {
            "immediate": True,
            "latency_ms": 15,
            "reject_rate": reject_rate,
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override submit_order to add rejection logic
        original_submit = exchange.submit_order
        async def rejecting_submit(order: OrderRequest) -> Dict[str, Any]:
            if random.random() < reject_rate:
                return {
                    "status": "rejected",
                    "order_id": f"mock_{order.client_order_id or 'unknown'}",
                    "reason": "RANDOM_REJECT",
                    "timestamp": time.time()
                }
            return await original_submit(order)

        exchange.submit_order = rejecting_submit
        return exchange

    @staticmethod
    def create_high_latency_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with high latency for performance testing."""
        config = {
            "immediate": True,
            "latency_ms": 500,  # 500ms latency
            "jitter_ms": 100,   # ±100ms jitter
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override to add jitter
        original_submit = exchange.submit_order
        async def jittery_submit(order: OrderRequest) -> Dict[str, Any]:
            result = await original_submit(order)
            # Add random jitter
            jitter = random.uniform(-config["jitter_ms"], config["jitter_ms"]) / 1000
            await asyncio.sleep(max(0, jitter))
            return result

        exchange.submit_order = jittery_submit
        return exchange

    @staticmethod
    def _generate_random_partial_ratios() -> List[float]:
        """Generate random partial fill ratios that sum to 1.0."""
        num_fills = random.randint(1, 4)
        ratios = [random.random() for _ in range(num_fills)]
        total = sum(ratios)
        return [r / total for r in ratios]

    @staticmethod
    def create_exchange_with_price_sequence(price_sequence: List[float],
                                          fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with specific price sequence for testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [0.5, 0.5],  # Two fills
            "price_sequence": price_sequence,
            **(fill_profile or {})
        }
        return MockExchange(config)


class MockExchange:
    """Mock exchange implementation with configurable behavior."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.orders = {}  # order_id -> order
        self.fills = {}   # order_id -> list of fills
        self.reject_next = None
        self.price_sequence = config.get("price_sequence", [])
        self.price_index = 0

    def set_fill_profile(self, profile: Dict[str, Any]):
        """Update fill profile dynamically."""
        self.config.update(profile)

    def set_reject_next_order(self, reason: str):
        """Set next order to be rejected."""
        self.reject_next = reason

    def reset_reject_pattern(self):
        """Reset rejection pattern."""
        self.reject_next = None

    def trigger_partial_fill(self, order_id: str, quantity: Decimal, price: Decimal):
        """Manually trigger a partial fill for testing."""
        if order_id not in self.fills:
            self.fills[order_id] = []

        fill = Fill(
            price=float(price),
            qty=float(quantity),
            fee=float(quantity * price * Decimal("0.001")),  # 0.1% fee
            fee_asset="USDT",
            ts_ns=int(time.time() * 1_000_000_000)
        )

        self.fills[order_id].append(fill)

    async def submit_order(self, order: OrderRequest) -> Dict[str, Any]:
        """Submit order with configurable behavior."""
        # Check for rejection
        if self.reject_next:
            reason = self.reject_next
            self.reject_next = None
            return {
                "status": "rejected",
                "order_id": f"mock_{order.client_order_id}",
                "reason": reason,
                "timestamp": time.time()
            }

        # Generate order ID
        order_id = f"mock_{order.client_order_id}_{int(time.time()*1000)}"
        self.orders[order_id] = order

        # Simulate exchange processing delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Determine fill behavior
        if self.config.get("immediate", True):
            await self._process_fills(order_id, order)
        else:
            # Schedule fills asynchronously
            asyncio.create_task(self._delayed_fill(order_id, order))

        return {
            "status": "accepted",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel order."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        # Simulate cancellation delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Remove from active orders
        del self.orders[order_id]

        return {
            "status": "cancelled",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        order = self.orders[order_id]
        fills = self.fills.get(order_id, [])
        filled_qty = sum(f.quantity for f in fills)

        if filled_qty == 0:
            status = "open"
        elif filled_qty < order.quantity:
            status = "partial_fill"
        else:
            status = "filled"

        return {
            "order_id": order_id,
            "status": status,
            "filled_quantity": filled_qty,
            "remaining_quantity": order.quantity - filled_qty,
            "fills": [f.dict() for f in fills]
        }

    async def get_order_fills(self, order_id: str) -> List[Fill]:
        """Get fills for order."""
        return self.fills.get(order_id, [])

    async def _process_fills(self, order_id: str, order: OrderRequest):
        """Process fills based on configuration."""
        partial_ratios = self.config.get("partial", [1.0])  # Default full fill

        if order_id not in self.fills:
            self.fills[order_id] = []

        remaining_qty = order.quantity

        for ratio in partial_ratios:
            if remaining_qty <= 0:
                break

            fill_qty = remaining_qty * Decimal(str(ratio))

            # Get price (from sequence or random)
            if self.price_sequence and self.price_index < len(self.price_sequence):
                price = Decimal(str(self.price_sequence[self.price_index]))
                self.price_index += 1
            else:
                # Generate realistic price based on order type
                if order.type.value == "market":
                    price = Decimal("50000") + Decimal(str(random.uniform(-1000, 1000)))
                else:
                    price = order.price or Decimal("50000")

            # Create fill
            fill = Fill(
                price=float(price),
                qty=float(fill_qty),
                fee=float(fill_qty * price * Decimal("0.001")),  # 0.1% fee
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )

            self.fills[order_id].append(fill)
            remaining_qty -= fill_qty

            # Simulate fill delay between partials
            if len(partial_ratios) > 1:
                await asyncio.sleep(0.05)

    async def _delayed_fill(self, order_id: str, order: OrderRequest):
        """Process delayed fills."""
        # Wait for configured delay
        delay = self.config.get("delay_ms", 100) / 1000
        await asyncio.sleep(delay)

        # Process fills if order still active
        if order_id in self.orders:
            await self._process_fills(order_id, order)


class MockExchangeFactory:
    """Factory for creating mock exchanges with different configurations."""

    @staticmethod
    def create_deterministic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create deterministic exchange for predictable testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [1.0],  # Full fill by default
            "price_sequence": [],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_stochastic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create stochastic exchange with random behavior."""
        config = {
            "immediate": True,
            "latency_ms": random.randint(5, 50),
            "partial": MockExchangeFactory._generate_random_partial_ratios(),
            "price_variation": 0.02,  # 2% price variation
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_slow_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create slow exchange for testing timeouts."""
        config = {
            "immediate": False,
            "latency_ms": 200,
            "delay_ms": 500,
            "partial": [1.0],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_partial_fill_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that does partial fills."""
        config = {
            "immediate": True,
            "latency_ms": 20,
            "partial": [0.3, 0.4, 0.3],  # Multiple partial fills
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_rejecting_exchange(reject_rate: float = 0.1, fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that randomly rejects orders."""
        config = {
            "immediate": True,
            "latency_ms": 15,
            "reject_rate": reject_rate,
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override submit_order to add rejection logic
        original_submit = exchange.submit_order
        async def rejecting_submit(order: OrderRequest) -> Dict[str, Any]:
            if random.random() < reject_rate:
                return {
                    "status": "rejected",
                    "order_id": f"mock_{order.client_order_id}",
                    "reason": "RANDOM_REJECT",
                    "timestamp": time.time()
                }
            return await original_submit(order)

        exchange.submit_order = rejecting_submit
        return exchange

    @staticmethod
    def create_high_latency_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with high latency for performance testing."""
        config = {
            "immediate": True,
            "latency_ms": 500,  # 500ms latency
            "jitter_ms": 100,   # ±100ms jitter
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override to add jitter
        original_submit = exchange.submit_order
        async def jittery_submit(order: OrderRequest) -> Dict[str, Any]:
            result = await original_submit(order)
            # Add random jitter
            jitter = random.uniform(-config["jitter_ms"], config["jitter_ms"]) / 1000
            await asyncio.sleep(max(0, jitter))
            return result

        exchange.submit_order = jittery_submit
        return exchange

    @staticmethod
    def _generate_random_partial_ratios() -> List[float]:
        """Generate random partial fill ratios that sum to 1.0."""
        num_fills = random.randint(1, 4)
        ratios = [random.random() for _ in range(num_fills)]
        total = sum(ratios)
        return [r / total for r in ratios]

    @staticmethod
    def create_exchange_with_price_sequence(price_sequence: List[float],
                                          fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with specific price sequence for testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [1.0],
            "price_sequence": price_sequence,
            **(fill_profile or {})
        }
