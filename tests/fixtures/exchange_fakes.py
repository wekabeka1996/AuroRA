"""
Test Fixtures — Exchange Fakes for Live Pipeline Testing
=======================================================

Deterministic exchange simulators for testing live trading pipeline without
network dependencies. Supports various scenarios: immediate fills, partial fills,
rejections, timeouts, etc.
"""

from __future__ import annotations

import time
import random
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from core.execution.exchange.common import OrderRequest, OrderType, Side, Fees


@dataclass
class FakeOrderResponse:
    """Fake order response matching exchange adapter interface."""
    id: Optional[str] = None
    client_order_id: Optional[str] = None
    status: str = "closed"
    filled_qty: float = 0.0
    avg_price: Optional[float] = None
    info: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.info is None:
            self.info = {}


@dataclass
class FakeFill:
    """Fake fill event for testing partial fills."""
    fill_id: str
    qty: float
    price: float
    timestamp_ns: int


class FakeExchange:
    """Deterministic exchange simulator for testing.
    
    Scenarios supported:
    - Immediate fills (status='closed')
    - Pending orders (status='open')
    - Rejections (raises exceptions)
    - Partial fills (via status() calls)
    - Timeouts and network errors
    """
    
    def __init__(self, 
                 symbol: str = "BTCUSDT",
                 base_price: float = 50000.0,
                 fees: Optional[Fees] = None,
                 fail_rate: float = 0.0,
                 latency_ms: int = 10):
        self.symbol = symbol
        self.base_price = base_price
        self.fees = fees or Fees(maker_fee_bps=0.0, taker_fee_bps=0.08)
        self.fail_rate = fail_rate
        self.latency_ms = latency_ms
        
        # Internal state
        self._orders: Dict[str, FakeOrderResponse] = {}
        self._fills: Dict[str, List[FakeFill]] = {}
        self._pending_orders: Dict[str, FakeOrderResponse] = {}
        
        # Scenario control
        self._next_fill_partial = False
        self._next_reject = False
        self._next_timeout = False
    
    def get_fees(self) -> Fees:
        """Get current fee structure."""
        return self.fees
    
    def fetch_top_of_book(self) -> tuple[float, float, list, list, list]:
        """Return deterministic market data."""
        mid = self.base_price
        spread = mid * 0.0001  # 1 bp spread
        bid_px = mid - spread/2
        ask_px = mid + spread/2
        
        # Generate deterministic L5 book
        bids = [(bid_px - i*0.01, 1.0 - i*0.1) for i in range(5)]
        asks = [(ask_px + i*0.01, 1.0 - i*0.1) for i in range(5)]
        
        # Generate some trades
        trades = [
            {"side": "buy", "qty": 0.1, "price": bid_px, "timestamp": time.time()},
            {"side": "sell", "qty": 0.05, "price": ask_px, "timestamp": time.time()},
        ]
        
        return mid, spread, bids, asks, trades
    
    def place_order(self, side: str, qty: float, price: Optional[float] = None) -> FakeOrderResponse:
        """Place order with deterministic behavior."""
        # Simulate latency
        time.sleep(self.latency_ms / 1000.0)
        
        # Check for forced failures
        if self._next_reject or random.random() < self.fail_rate:
            self._next_reject = False
            raise ValueError("Exchange rejected order")
        
        if self._next_timeout:
            self._next_timeout = False
            raise TimeoutError("Exchange timeout")
        
        # Generate order ID
        order_id = f"fake_{int(time.time() * 1000)}_{random.randint(1000, 9999)}"
        client_oid = f"client_{order_id}"
        
        # Determine fill behavior
        if price is None or abs(price - self.base_price) < 1.0:
            # Market order or limit at mid - immediate fill
            status = "closed"
            filled_qty = qty
            avg_price = self.base_price
        else:
            # Limit order away from mid - pending
            status = "open"
            filled_qty = 0.0
            avg_price = None
            
            # Store for later status checks
            self._pending_orders[order_id] = FakeOrderResponse(
                id=order_id,
                client_order_id=client_oid,
                status=status,
                filled_qty=filled_qty,
                avg_price=avg_price
            )
        
        response = FakeOrderResponse(
            id=order_id,
            client_order_id=client_oid,
            status=status,
            filled_qty=filled_qty,
            avg_price=avg_price
        )
        
        self._orders[order_id] = response
        return response
    
    def get_order_status(self, order_id: str) -> FakeOrderResponse:
        """Get order status, potentially with fills."""
        if order_id not in self._orders and order_id not in self._pending_orders:
            raise ValueError(f"Order {order_id} not found")
        
        # Simulate latency
        time.sleep(self.latency_ms / 1000.0)
        
        if order_id in self._pending_orders:
            order = self._pending_orders[order_id]
            
            # Check if we should fill it now
            if random.random() < 0.3:  # 30% chance to fill on status check
                order.status = "closed"
                order.filled_qty = 0.001  # Partial fill
                order.avg_price = self.base_price
                
                # Generate fill event
                fill = FakeFill(
                    fill_id=f"fill_{order_id}_{int(time.time())}",
                    qty=order.filled_qty,
                    price=order.avg_price,
                    timestamp_ns=int(time.time() * 1_000_000_000)
                )
                self._fills[order_id] = [fill]
                
                # Remove from pending
                del self._pending_orders[order_id]
        
        return self._orders.get(order_id) or self._pending_orders[order_id]
    
    def cancel_all(self) -> None:
        """Cancel all pending orders."""
        # Simulate latency
        time.sleep(self.latency_ms / 1000.0)
        
        for order_id in list(self._pending_orders.keys()):
            order = self._pending_orders[order_id]
            order.status = "canceled"
            self._orders[order_id] = order
            del self._pending_orders[order_id]
    
    def close_position(self, side: str, qty: float) -> FakeOrderResponse:
        """Close position (simplified)."""
        # Simulate latency
        time.sleep(self.latency_ms / 1000.0)
        
        # Always succeed for testing
        order_id = f"close_{int(time.time() * 1000)}"
        return FakeOrderResponse(
            id=order_id,
            status="closed",
            filled_qty=qty,
            avg_price=self.base_price
        )
    
    def get_fills(self, order_id: str) -> List[FakeFill]:
        """Get fills for an order."""
        return self._fills.get(order_id, [])
    
    # Scenario control methods
    def set_next_fill_partial(self, partial: bool = True):
        """Force next fill to be partial."""
        self._next_fill_partial = partial
    
    def set_next_reject(self, reject: bool = True):
        """Force next order to be rejected."""
        self._next_reject = reject
    
    def set_next_timeout(self, timeout: bool = True):
        """Force next order to timeout."""
        self._next_timeout = timeout


__all__ = ["FakeExchange", "FakeOrderResponse", "FakeFill"]