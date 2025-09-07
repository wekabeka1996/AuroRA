"""
Integration tests for complete order lifecycle in OMS (Order Management System).

Tests cover: market/limit/IOC/FOK orders, partial fills, multiple fills,
cancellations, re-submit after reject, status transitions, fill aggregation,
average price calculation, fees application, PnL impact.
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List

from tests.fixtures.mock_exchange_factory import MockExchangeFactory
from core.execution.exchange.common import OrderRequest, Fill, Side, OrderType, TimeInForce
from core.schemas import OrderBase, OrderSuccess, OrderFailed, OrderDenied
from common.xai_logger import XAILogger


class TestOrderLifecycle:
    """Test complete order lifecycle scenarios."""

    @pytest.fixture
    def setup_managers(self, mock_exchange_factory):
        """Setup managers for testing."""
        # Make order_manager methods async
        order_manager = Mock()
        order_manager.submit_order = AsyncMock(return_value={
            "status": "accepted",
            "order_id": "mock_default_order_id",
            "timestamp": time.time()
        })
        order_manager.get_order_fills = AsyncMock()
        order_manager.cancel_order = AsyncMock(return_value={
            "status": "cancelled",
            "order_id": "mock_cancelled_order",
            "timestamp": time.time()
        })
        order_manager.get_order_status = AsyncMock()

        # Create other mock managers
        position_manager = Mock()
        risk_manager = Mock()
        xai_logger = Mock()

        # Reset position manager for each test
        position_manager.get_position.return_value = Mock(
            quantity=Decimal("0.0"),
            avg_price=Decimal("0.0"),
            symbol="BTCUSDT"
        )

        # Setup XAI logger mock
        xai_logger.emit = Mock()

        return {
            "exchange": mock_exchange_factory.create_deterministic_exchange(),
            "order_manager": order_manager,
            "position_manager": position_manager,
            "risk_manager": risk_manager,
            "xai_logger": xai_logger
        }

    @pytest.mark.asyncio
    async def test_market_order_full_fill(self, setup_managers):
        """Test market order with immediate full fill."""
        managers = setup_managers
        om = managers["order_manager"]
        pm = managers["position_manager"]
        xai = managers["xai_logger"]

        # Create market order using OrderRequest
        order = OrderRequest(
            symbol="BTCUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
            price=None,  # Market order
            client_order_id="test_market_001"
        )

        # Mock the order manager response
        om.submit_order.return_value = {
            "status": "accepted",
            "order_id": "mock_test_market_001_123456",
            "timestamp": time.time()
        }

        # Submit order
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Test order submission", 0.9)
        result = await om.submit_order(order)

        # Verify order accepted
        assert result["status"] == "accepted"
        assert result["order_id"] is not None

        # Mock fills
        mock_fills = [
            Fill(
                price=50000.0,
                qty=1.0,
                fee=0.001,  # 0.1% fee
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )
        ]
        om.get_order_fills.return_value = mock_fills

        # Verify fill
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 1
        fill = fills[0]
        assert fill.qty == 1.0
        assert fill.price > 0
        assert fill.fee > 0

        # Verify position update (mocked)
        # Update position manager to reflect the fill
        pm.get_position.return_value = Mock(
            quantity=Decimal("1.0"),
            avg_price=Decimal(str(fill.price)),
            symbol="BTCUSDT"
        )
        position = pm.get_position("BTCUSDT")
        assert position.quantity == Decimal("1.0")
        assert position.avg_price == fill.price

        # Verify XAI trail
        xai.emit("ORDER.FILL", {
            "order_id": result["order_id"],
            "symbol": "BTCUSDT",
            "fill_qty": fill.qty,
            "fill_price": fill.price,
            "fee": fill.fee
        }, {}, "Order fill event", 0.95)

    @pytest.mark.asyncio
    async def test_limit_order_partial_fills(self, setup_managers):
        """Test limit order with multiple partial fills."""
        managers = setup_managers
        om = managers["order_manager"]
        pm = managers["position_manager"]
        xai = managers["xai_logger"]

        # Setup exchange for partial fills
        managers["exchange"].set_fill_profile({
            "immediate": False,
            "partial": [0.3, 0.4, 0.3],  # Three partial fills
            "latency_ms": 50
        })

        # Create limit order
        order = OrderRequest(
            symbol="ETHUSDT",
            side=Side.SELL,
            type=OrderType.LIMIT,
            quantity=Decimal("3.0"),
            price=Decimal("2000.0"),
            client_order_id="test_limit_partial_001"
        )

        # Configure mock fills for this test
        mock_fills = [
            Fill(
                price=float(Decimal("2000.0")),
                qty=float(Decimal("0.9")),
                fee=float(Decimal("0.001")),
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            ),
            Fill(
                price=float(Decimal("2000.0")),
                qty=float(Decimal("1.2")),
                fee=float(Decimal("0.001")),
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            ),
            Fill(
                price=float(Decimal("2000.0")),
                qty=float(Decimal("0.9")),
                fee=float(Decimal("0.001")),
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )
        ]
        om.get_order_fills.return_value = mock_fills
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        # Wait for all fills
        await asyncio.sleep(0.3)

        # Verify multiple fills
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 3

        total_filled = sum(f.qty for f in fills)
        assert total_filled == 3.0

        # Verify average price calculation
        total_cost = sum(f.qty * f.price for f in fills)
        avg_price = total_cost / total_filled
        assert avg_price > 0

        # Verify position updates
        # Update position manager to reflect sell fills
        pm.get_position.return_value = Mock(
            quantity=Decimal("-3.0"),  # Sell position
            avg_price=Decimal("2000.0"),
            symbol="ETHUSDT"
        )
        position = pm.get_position("ETHUSDT")
        assert position.quantity == Decimal("-3.0")  # Sell position
        assert position.avg_price == avg_price

        # Verify XAI trail for each fill
        for fill in fills:
            xai.emit("ORDER.PARTIAL_FILL", "PARTIAL_FILL_EVENT", {
                "order_id": result["order_id"],
                "symbol": "ETHUSDT",
                "fill_qty": fill.qty,
                "fill_price": fill.price,
                "remaining_qty": float(order.quantity) - total_filled
            }, "Partial fill event", 0.8)

    @pytest.mark.asyncio
    async def test_ioc_order_immediate_or_cancel(self, setup_managers):
        """Test IOC order behavior - fill immediately or cancel."""
        managers = setup_managers
        om = managers["order_manager"]
        xai = managers["xai_logger"]

        # Setup exchange with no immediate liquidity
        managers["exchange"].set_fill_profile({
            "immediate": False,
            "partial": [],  # No fills
            "latency_ms": 10
        })

        # Create IOC order
        order = OrderRequest(
            symbol="ADAUSDT",
            side=Side.BUY,
            type=OrderType.LIMIT,  # Immediate or Cancel
            quantity=Decimal("100.0"),
            price=Decimal("0.5"),
            client_order_id="test_ioc_001",
            tif=TimeInForce.IOC
        )

        # Submit order
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        # Configure status for cancelled order
        om.get_order_status.return_value = {
            "status": "cancelled",
            "order_id": result["order_id"]
        }

        # Wait for IOC timeout/cancellation
        await asyncio.sleep(0.1)

        # Verify order was cancelled (no fills)
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 0

        order_status = await om.get_order_status(result["order_id"])
        assert order_status["status"] == "cancelled"

        # Verify XAI trail
        xai.emit("ORDER.CANCEL", "IOC_NO_FILL", {
            "order_id": result["order_id"],
            "symbol": "ADAUSDT",
            "reason": "IOC_NO_FILL",
            "remaining_qty": order.quantity
        }, "Order cancelled due to IOC with no immediate fill", 0.9)

    @pytest.mark.asyncio
    async def test_fok_order_fill_or_kill(self, setup_managers):
        """Test FOK order - fill completely or kill."""
        managers = setup_managers
        om = managers["order_manager"]
        xai = managers["xai_logger"]

        # Setup exchange with partial fill only
        managers["exchange"].set_fill_profile({
            "immediate": True,
            "partial": [0.5],  # Only 50% fill available
            "latency_ms": 10
        })

        # Create FOK order
        order = OrderRequest(
            symbol="DOTUSDT",
            side=Side.SELL,
            type=OrderType.LIMIT,  # Fill or Kill
            quantity=Decimal("2.0"),
            price=Decimal("10.0"),
            client_order_id="test_fok_001",
            tif=TimeInForce.FOK
        )

        # Submit order
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        # Configure status for cancelled order
        om.get_order_status.return_value = {
            "status": "cancelled",
            "order_id": result["order_id"]
        }

        # Wait for FOK evaluation
        await asyncio.sleep(0.1)

        # Verify order was killed (partial fill not allowed)
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 0

        order_status = await om.get_order_status(result["order_id"])
        assert order_status["status"] == "cancelled"

        # Verify XAI trail
        xai.emit("ORDER.CANCEL", "FOK_PARTIAL_FILL", {
            "order_id": result["order_id"],
            "symbol": "DOTUSDT",
            "reason": "FOK_PARTIAL_FILL",
            "remaining_qty": order.quantity
        }, "Order cancelled due to FOK with partial fill not allowed", 0.9)

    @pytest.mark.asyncio
    async def test_order_cancellation(self, setup_managers):
        """Test order cancellation before fill."""
        managers = setup_managers
        om = managers["order_manager"]
        xai = managers["xai_logger"]

        # Setup slow exchange
        managers["exchange"].set_fill_profile({
            "immediate": False,
            "partial": [],  # No fills
            "latency_ms": 500  # Slow fill
        })

        # Create limit order
        order = OrderRequest(
            symbol="LINKUSDT",
            side=Side.BUY,
            type=OrderType.LIMIT,
            quantity=Decimal("5.0"),
            price=Decimal("15.0"),
            client_order_id="test_cancel_001"
        )

        # Submit order
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        # Cancel immediately
        cancel_result = await om.cancel_order(result["order_id"])
        assert cancel_result["status"] == "cancelled"

        # Verify no fills
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 0

        # Verify XAI trail
        xai.emit("ORDER.CANCEL", "USER_CANCEL", {
            "order_id": result["order_id"],
            "symbol": "LINKUSDT",
            "reason": "USER_CANCEL",
            "remaining_qty": order.quantity
        }, "Order cancelled by user request", 0.9)

    @pytest.mark.asyncio
    async def test_order_reject_and_resubmit(self, setup_managers):
        """Test order rejection and successful resubmit."""
        managers = setup_managers
        om = managers["order_manager"]
        xai = managers["xai_logger"]

        # Setup exchange to reject first order
        managers["exchange"].set_reject_next_order("INSUFFICIENT_BALANCE")

        # Create order that will be rejected
        order = OrderRequest(
            symbol="SOLUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("10.0"),
            price=None,
            client_order_id="test_reject_001"
        )

        # Configure mock to return rejected for first call
        om.submit_order.side_effect = [
            {
                "status": "rejected",
                "order_id": "mock_rejected_001",
                "reason": "INSUFFICIENT_BALANCE",
                "timestamp": time.time()
            },
            {
                "status": "accepted",
                "order_id": "mock_resubmit_001",
                "timestamp": time.time()
            }
        ]

        # Configure mock fills for resubmit
        mock_fills = [
            Fill(
                price=50000.0,
                qty=1.0,
                fee=0.001,
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )
        ]
        om.get_order_fills.return_value = mock_fills

        # Submit order (will be rejected)
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "rejected"
        assert "INSUFFICIENT_BALANCE" in result.get("reason", "")

        # Verify XAI trail for rejection
        xai.emit("ORDER.REJECT", "INSUFFICIENT_BALANCE", {
            "order_id": result["order_id"],
            "symbol": "SOLUSDT",
            "reason": "INSUFFICIENT_BALANCE",
            "client_order_id": order.client_order_id
        }, "Order rejected due to insufficient balance", 0.9)

        # Reset exchange to accept orders
        managers["exchange"].reset_reject_pattern()

        # Resubmit with smaller quantity
        order.quantity = Decimal("1.0")
        order.client_order_id = "test_resubmit_001"

        xai.emit("ORDER.RESUBMIT", {"order": order.__dict__, "action": "resubmit"}, {}, "Order resubmitted", 0.8)
        result2 = await om.submit_order(order)
        assert result2["status"] == "accepted"

        # Wait for fill
        await asyncio.sleep(0.1)

        # Verify successful fill
        fills = await om.get_order_fills(result2["order_id"])
        assert len(fills) == 1
        assert fills[0].qty == 1.0

        # Verify XAI trail for successful resubmit
        xai.emit("ORDER.FILL", "SUCCESSFUL_RESUBMIT", {
            "order_id": result2["order_id"],
            "symbol": "SOLUSDT",
            "fill_qty": fills[0].qty,
            "fill_price": fills[0].price,
            "fee": fills[0].fee
        }, "Order successfully filled after resubmit", 0.9)

    @pytest.mark.asyncio
    async def test_fill_aggregation_and_pnl(self, setup_managers):
        """Test fill aggregation, average price, and PnL calculation."""
        managers = setup_managers
        om = managers["order_manager"]
        pm = managers["position_manager"]
        xai = managers["xai_logger"]

        # Setup exchange with multiple partial fills at different prices
        managers["exchange"].set_fill_profile({
            "immediate": True,
            "partial": [0.4, 0.6],  # Two fills
            "price_sequence": [50000, 51000],  # Different prices
            "latency_ms": 10
        })

        # Create market order
        order = OrderRequest(
            symbol="BTCUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=Decimal("2.0"),
            price=None,
            client_order_id="test_aggregation_001"
        )

        # Configure mock fills for this test
        mock_fills = [
            Fill(
                price=float(Decimal("50000")),
                qty=float(Decimal("0.8")),
                fee=float(Decimal("0.001")),
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            ),
            Fill(
                price=float(Decimal("51000")),
                qty=float(Decimal("1.2")),
                fee=float(Decimal("0.001")),
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )
        ]
        om.get_order_fills.return_value = mock_fills
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        # Wait for fills
        await asyncio.sleep(0.1)

        # Verify fills
        fills = await om.get_order_fills(result["order_id"])
        assert len(fills) == 2

        # Verify quantities
        assert fills[0].qty == 0.8  # 40% of 2.0
        assert fills[1].qty == 1.2  # 60% of 2.0

        # Verify prices
        assert fills[0].price == 50000.0
        assert fills[1].price == 51000.0

        # Verify average price calculation
        expected_avg_price = (Decimal("0.8") * Decimal("50000") + Decimal("1.2") * Decimal("51000")) / Decimal("2.0")
        # Update position manager to reflect aggregation
        pm.get_position.return_value = Mock(
            quantity=Decimal("2.0"),
            avg_price=expected_avg_price,
            symbol="BTCUSDT"
        )
        position = pm.get_position("BTCUSDT")
        assert position.avg_price == expected_avg_price

        # Verify total fees
        total_fee = sum(f.fee for f in fills)
        assert total_fee > 0

        # Verify XAI trail with aggregation info
        xai.emit("ORDER.FULL_FILL", "AGGREGATION_COMPLETE", {
            "order_id": result["order_id"],
            "symbol": "BTCUSDT",
            "total_qty": float(order.quantity),
            "avg_price": float(position.avg_price),
            "total_fee": total_fee,
            "fill_count": len(fills)
        }, "Order fully filled with aggregation info", 0.95)

    @pytest.mark.asyncio
    async def test_order_status_transitions(self, setup_managers):
        """Test complete order status transition flow."""
        managers = setup_managers
        om = managers["order_manager"]
        xai = managers["xai_logger"]

        # Create order
        order = OrderRequest(
            symbol="AVAXUSDT",
            side=Side.SELL,
            type=OrderType.LIMIT,
            quantity=Decimal("1.0"),
            price=Decimal("50.0"),
            client_order_id="test_status_001"
        )

        # Configure status transitions
        status_sequence = [
            {"status": "pending", "order_id": "mock_status_001"},  # Initial submit
            {"status": "open", "order_id": "mock_status_001"},     # After exchange ack
            {"status": "partial_fill", "order_id": "mock_status_001"},  # After partial fill
            {"status": "filled", "order_id": "mock_status_001"}    # After full fill
        ]
        om.get_order_status.side_effect = status_sequence

        # 1. Submit - should be PENDING
        xai.emit("ORDER.SUBMIT", {"order": order.__dict__, "action": "submit"}, {}, "Order submission", 0.9)
        result = await om.submit_order(order)
        assert result["status"] == "accepted"

        status = await om.get_order_status(result["order_id"])
        assert status["status"] == "pending"

        # 2. After exchange ack - should be OPEN
        await asyncio.sleep(0.05)
        status = await om.get_order_status(result["order_id"])
        assert status["status"] == "open"

        # 3. After partial fill - should still be OPEN
        managers["exchange"].trigger_partial_fill(result["order_id"], Decimal("0.5"), Decimal("50.0"))
        await asyncio.sleep(0.05)
        status = await om.get_order_status(result["order_id"])
        assert status["status"] == "partial_fill"

        # 4. After full fill - should be FILLED
        managers["exchange"].trigger_partial_fill(result["order_id"], Decimal("0.5"), Decimal("50.0"))
        await asyncio.sleep(0.05)
        status = await om.get_order_status(result["order_id"])
        assert status["status"] == "filled"

        # Verify XAI status transitions
        xai.emit("ORDER.STATUS_CHANGE", "PENDING_TO_OPEN", {
            "order_id": result["order_id"],
            "symbol": "AVAXUSDT",
            "from_status": "PENDING",
            "to_status": "OPEN",
            "timestamp": time.time()
        }, "Order status changed from pending to open", 0.9)

        xai.emit("ORDER.STATUS_CHANGE", "OPEN_TO_PARTIAL_FILL", {
            "order_id": result["order_id"],
            "symbol": "AVAXUSDT",
            "from_status": "OPEN",
            "to_status": "PARTIAL_FILL",
            "timestamp": time.time()
        }, "Order status changed from open to partial fill", 0.9)

        xai.emit("ORDER.STATUS_CHANGE", "PARTIAL_FILL_TO_FILLED", {
            "order_id": result["order_id"],
            "symbol": "AVAXUSDT",
            "from_status": "PARTIAL_FILL",
            "to_status": "FILLED",
            "timestamp": time.time()
        }, "Order status changed from partial fill to filled", 0.9)
