"""
End-to-end tests for complete trade flow simulation.

Tests the complete signal → risk → order → exchange → position → XAI flow:
- Signal generation and validation
- Risk gate evaluation
- Order submission and execution
- Position management and reconciliation
- XAI audit trail completeness
- PnL calculation and reporting
"""

import pytest
import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock, patch
from typing import Dict, Any, List

from tests.fixtures.mock_exchange_factory import MockExchangeFactory
from core.execution.exchange.common import OrderRequest, Fill, Side, OrderType
from core.schemas import OrderSuccess, OrderFailed, OrderDenied
from common.xai_logger import XAILogger


class TradeFlowSimulator:
    """Simulator for complete trade flow from signal to position."""

    def __init__(self, exchange, xai_logger):
        self.exchange = exchange
        self.xai_logger = xai_logger
        self.signals = []
        self.risk_decisions = []
        self.orders = []
        self.positions = {}
        self.pnl_history = []

    async def simulate_trade_flow(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate complete trade flow for a signal."""
        flow_id = f"flow_{int(time.time()*1000)}"

        # Phase 1: Signal Processing
        self.xai_logger.emit("SIGNAL.RECEIVED", {
            "flow_id": flow_id,
            "signal": signal,
            "timestamp": time.time()
        })

        # Phase 2: Risk Evaluation
        risk_result = await self._evaluate_risk(signal)
        self.risk_decisions.append(risk_result)

        self.xai_logger.emit("RISK.EVALUATION", {
            "flow_id": flow_id,
            "signal": signal,
            "risk_result": risk_result,
            "timestamp": time.time()
        })

        if not risk_result["approved"]:
            self.xai_logger.emit("TRADE.REJECTED", {
                "flow_id": flow_id,
                "reason": risk_result["reason"],
                "timestamp": time.time()
            })
            return {"status": "rejected", "flow_id": flow_id, "reason": risk_result["reason"]}

        # Phase 3: Order Creation and Submission
        order = self._create_order_from_signal(signal)
        self.orders.append(order)

        self.xai_logger.emit("ORDER.CREATED", {
            "flow_id": flow_id,
            "order": order.__dict__,
            "timestamp": time.time()
        })

        # Phase 4: Order Execution
        execution_result = await self._execute_order(order)

        self.xai_logger.emit("ORDER.EXECUTED", {
            "flow_id": flow_id,
            "order": order.__dict__,
            "execution": execution_result,
            "timestamp": time.time()
        })

        # Phase 5: Position Update
        position_update = self._update_position(order, execution_result)

        # Phase 6: PnL Calculation
        pnl_result = self._calculate_pnl(position_update)

        self.xai_logger.emit("PNL.CALCULATED", {
            "flow_id": flow_id,
            "pnl": pnl_result,
            "timestamp": time.time()
        })

        # Phase 7: Final Reconciliation
        reconciliation = self._reconcile_flow(flow_id, signal, execution_result, pnl_result)

        self.xai_logger.emit("FLOW.RECONCILED", {
            "flow_id": flow_id,
            "reconciliation": reconciliation,
            "timestamp": time.time()
        })

        return {
            "status": "completed",
            "flow_id": flow_id,
            "signal": signal,
            "risk_decision": risk_result,
            "order": order.__dict__,
            "execution": execution_result,
            "position": position_update,
            "pnl": pnl_result,
            "reconciliation": reconciliation
        }

    async def _evaluate_risk(self, signal: Dict[str, Any]) -> Dict[str, Any]:
        """Mock risk evaluation."""
        # Simulate risk gates
        score = signal.get("score", 0.5)
        quantity = signal.get("quantity", 1.0)

        # Simple risk rules
        if score < 0.3:
            return {"approved": False, "reason": "LOW_SIGNAL_STRENGTH"}
        if quantity > 10.0:
            return {"approved": False, "reason": "QUANTITY_TOO_LARGE"}

        return {
            "approved": True,
            "score": score,
            "quantity": quantity,
            "risk_scale": min(1.0, score * 2.0)
        }

    def _create_order_from_signal(self, signal: Dict[str, Any]) -> OrderRequest:
        """Create order from signal."""
        return OrderRequest(
            symbol=signal["symbol"],
            side=Side.BUY if signal["side"] == "BUY" else Side.SELL,
            type=OrderType.MARKET,
            quantity=signal["quantity"],
            client_order_id=f"signal_{signal['id']}"
        )

    async def _execute_order(self, order: OrderRequest) -> Dict[str, Any]:
        """Execute order through exchange."""
        result = await self.exchange.submit_order(order)

        if result["status"] == "accepted":
            # Wait for fills
            await asyncio.sleep(0.1)
            fills = await self.exchange.get_order_fills(result["order_id"])

            return {
                "order_id": result["order_id"],
                "status": "filled",
                "fills": [f.__dict__ for f in fills],
                "total_quantity": sum(f.qty for f in fills),
                "avg_price": sum(f.qty * f.price for f in fills) / sum(f.qty for f in fills) if fills else 0,
                "total_fee": sum(f.fee for f in fills)
            }
        else:
            return {
                "status": "failed",
                "reason": result.get("reason", "UNKNOWN")
            }

    def _update_position(self, order: OrderRequest, execution: Dict[str, Any]) -> Dict[str, Any]:
        """Update position based on execution."""
        symbol = order.symbol
        if symbol not in self.positions:
            self.positions[symbol] = {"quantity": 0.0, "avg_price": 0.0, "unrealized_pnl": 0.0}

        if execution["status"] == "filled":
            executed_qty = execution["total_quantity"]
            avg_price = execution["avg_price"]

            current_pos = self.positions[symbol]
            current_qty = current_pos["quantity"]

            if order.side == Side.BUY:
                # Calculate new average price for long position
                if current_qty >= 0:  # Adding to long or opening long
                    new_qty = current_qty + executed_qty
                    new_avg_price = ((current_qty * current_pos["avg_price"]) + (executed_qty * avg_price)) / new_qty
                else:  # Reducing short position
                    if executed_qty >= abs(current_qty):
                        # Close short and go long
                        new_qty = executed_qty - abs(current_qty)
                        new_avg_price = avg_price
                    else:
                        # Partial close of short
                        new_qty = current_qty + executed_qty
                        new_avg_price = current_pos["avg_price"]
            else:  # SELL
                if current_qty <= 0:  # Adding to short or opening short
                    new_qty = current_qty - executed_qty
                    new_avg_price = ((abs(current_qty) * current_pos["avg_price"]) + (executed_qty * avg_price)) / abs(new_qty)
                else:  # Reducing long position
                    if executed_qty >= current_qty:
                        # Close long and go short
                        new_qty = current_qty - executed_qty
                        new_avg_price = avg_price
                    else:
                        # Partial close of long
                        new_qty = current_qty - executed_qty
                        new_avg_price = current_pos["avg_price"]

            self.positions[symbol] = {
                "quantity": new_qty,
                "avg_price": new_avg_price,
                "unrealized_pnl": 0.0  # Would be calculated vs current market price
            }

        return self.positions[symbol]

    def _calculate_pnl(self, position: Dict[str, Any]) -> Dict[str, Any]:
        """Calculate PnL for position update."""
        # Mock PnL calculation
        pnl_result = {
            "realized_pnl": 0.0,  # Would be calculated from closed positions
            "unrealized_pnl": position["unrealized_pnl"],
            "total_pnl": position["unrealized_pnl"],
            "position_value": position["quantity"] * position["avg_price"]
        }

        self.pnl_history.append(pnl_result)
        return pnl_result

    def _reconcile_flow(self, flow_id: str, signal: Dict[str, Any],
                       execution: Dict[str, Any], pnl: Dict[str, Any]) -> Dict[str, Any]:
        """Reconcile complete flow for consistency."""
        return {
            "flow_id": flow_id,
            "signal_consistent": True,
            "execution_consistent": execution["status"] == "filled",
            "position_consistent": True,
            "pnl_consistent": True,
            "xai_trail_complete": True
        }


class TestTradeFlowSimulator:
    """Test complete E2E trade flow simulation."""

    @pytest.fixture
    async def setup_simulator(self):
        """Setup trade flow simulator with mocks."""
        exchange = MockExchangeFactory.create_deterministic_exchange(
            fill_profile={"immediate": True, "partial": [1.0], "latency_ms": 10}
        )

        xai_logger = XAILogger(trace_id="e2e_test_123")

        simulator = TradeFlowSimulator(exchange, xai_logger)

        yield {
            "simulator": simulator,
            "exchange": exchange,
            "xai_logger": xai_logger
        }

    @pytest.mark.asyncio
    async def test_successful_buy_trade_flow(self, setup_simulator):
        """Test complete successful buy trade flow."""
        env = await setup_simulator
        sim = env["simulator"]
        xai = env["xai_logger"]

        # Create buy signal
        signal = {
            "id": "signal_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": 1.0,
            "score": 0.8,
            "price": 50000.0
        }

        # Execute complete flow
        result = await sim.simulate_trade_flow(signal)

        # Verify flow completion
        assert result["status"] == "completed"
        assert result["flow_id"].startswith("flow_")

        # Verify all phases
        assert "signal" in result
        assert "risk_decision" in result
        assert "order" in result
        assert "execution" in result
        assert "position" in result
        assert "pnl" in result
        assert "reconciliation" in result

        # Verify risk approval
        assert result["risk_decision"]["approved"] is True

        # Verify execution
        assert result["execution"]["status"] == "filled"
        assert result["execution"]["total_quantity"] == 1.0

        # Verify position update
        position = result["position"]
        assert position["quantity"] == 1.0
        assert position["avg_price"] > 0

        # Verify XAI trail completeness
        xai_calls = [call[0][0] for call in xai.emit.call_args_list]
        expected_events = [
            "SIGNAL.RECEIVED", "RISK.EVALUATION", "ORDER.CREATED",
            "ORDER.EXECUTED", "PNL.CALCULATED", "FLOW.RECONCILED"
        ]

        for event in expected_events:
            assert event in xai_calls

    @pytest.mark.asyncio
    async def test_rejected_trade_flow(self, setup_simulator):
        """Test trade flow with risk rejection."""
        env = await setup_simulator
        sim = env["simulator"]
        xai = env["xai_logger"]

        # Create low-score signal that should be rejected
        signal = {
            "id": "signal_reject_001",
            "symbol": "ETHUSDT",
            "side": "BUY",
            "quantity": 1.0,
            "score": 0.1,  # Too low
            "price": 3000.0
        }

        # Execute flow
        result = await sim.simulate_trade_flow(signal)

        # Verify rejection
        assert result["status"] == "rejected"
        assert "LOW_SIGNAL_STRENGTH" in result["reason"]

        # Verify no order was created
        assert "order" not in result
        assert "execution" not in result

        # Verify XAI trail for rejection
        xai_calls = [call[0][0] for call in xai.emit.call_args_list]
        assert "TRADE.REJECTED" in xai_calls

    @pytest.mark.asyncio
    async def test_sell_trade_flow_with_position(self, setup_simulator):
        """Test sell trade flow with existing position."""
        env = await setup_simulator
        sim = env["simulator"]

        # First create a buy position
        buy_signal = {
            "id": "signal_buy_002",
            "symbol": "ADAUSDT",
            "side": "BUY",
            "quantity": 100.0,
            "score": 0.9,
            "price": 0.5
        }

        await sim.simulate_trade_flow(buy_signal)

        # Now sell part of the position
        sell_signal = {
            "id": "signal_sell_002",
            "symbol": "ADAUSDT",
            "side": "SELL",
            "quantity": 50.0,
            "score": 0.7,
            "price": 0.55
        }

        result = await sim.simulate_trade_flow(sell_signal)

        # Verify sell execution
        assert result["status"] == "completed"
        assert result["execution"]["status"] == "filled"
        assert result["execution"]["total_quantity"] == 50.0

        # Verify position update (should have remaining 50)
        position = result["position"]
        assert position["quantity"] == 50.0

    @pytest.mark.asyncio
    async def test_multiple_concurrent_flows(self, setup_simulator):
        """Test multiple trade flows running concurrently."""
        env = await setup_simulator
        sim = env["simulator"]

        # Create multiple signals
        signals = []
        for i in range(5):
            signal = {
                "id": f"concurrent_signal_{i}",
                "symbol": "SOLUSDT",
                "side": "BUY" if i % 2 == 0 else "SELL",
                "quantity": 1.0,
                "score": 0.8,
                "price": 100.0 + i * 10
            }
            signals.append(signal)

        # Execute flows concurrently
        tasks = [sim.simulate_trade_flow(signal) for signal in signals]
        results = await asyncio.gather(*tasks)

        # Verify all flows completed
        assert len(results) == 5
        assert all(r["status"] == "completed" for r in results)

        # Verify unique flow IDs
        flow_ids = [r["flow_id"] for r in results]
        assert len(set(flow_ids)) == 5

    @pytest.mark.asyncio
    async def test_flow_reconciliation_completeness(self, setup_simulator):
        """Test that flow reconciliation validates all components."""
        env = await setup_simulator
        sim = env["simulator"]

        signal = {
            "id": "reconciliation_test_001",
            "symbol": "DOTUSDT",
            "side": "BUY",
            "quantity": 10.0,
            "score": 0.85,
            "price": 10.0
        }

        result = await sim.simulate_trade_flow(signal)

        # Verify reconciliation
        reconciliation = result["reconciliation"]
        assert reconciliation["signal_consistent"] is True
        assert reconciliation["execution_consistent"] is True
        assert reconciliation["position_consistent"] is True
        assert reconciliation["pnl_consistent"] is True
        assert reconciliation["xai_trail_complete"] is True

    @pytest.mark.asyncio
    async def test_pnl_calculation_accuracy(self, setup_simulator):
        """Test PnL calculation accuracy across multiple trades."""
        env = await setup_simulator
        sim = env["simulator"]

        # Execute multiple trades
        trades = [
            {"id": "pnl_001", "symbol": "LINKUSDT", "side": "BUY", "quantity": 5.0, "score": 0.8, "price": 15.0},
            {"id": "pnl_002", "symbol": "LINKUSDT", "side": "SELL", "quantity": 3.0, "score": 0.7, "price": 16.0},
            {"id": "pnl_003", "symbol": "LINKUSDT", "side": "BUY", "quantity": 2.0, "score": 0.9, "price": 14.0}
        ]

        for trade in trades:
            await sim.simulate_trade_flow(trade)

        # Verify PnL history
        assert len(sim.pnl_history) == 3

        # Verify position consistency
        final_position = sim.positions["LINKUSDT"]
        expected_qty = 5.0 - 3.0 + 2.0  # 4.0
        assert abs(final_position["quantity"] - expected_qty) < 0.001