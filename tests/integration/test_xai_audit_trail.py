"""
XAI Audit Trail tests for live trade flow validation.

Tests XAI audit trail completeness and integrity:
- Event logging completeness for trade flows
- XAI event structure validation
- Audit trail correlation across components
- Event sequencing and causality
- Performance impact of audit logging
"""

import pytest
import asyncio
import time
import json
from unittest.mock import Mock, patch, MagicMock
from typing import Dict, Any, List
import tempfile
import os

from tests.fixtures.mock_exchange_factory import MockExchangeFactory
from tests.e2e.test_trade_flow_simulator import TradeFlowSimulator
from core.execution.exchange.common import OrderRequest, Side, OrderType
from common.xai_logger import XAILogger


class XAIAuditTrailValidator:
    """Validator for XAI audit trail completeness and integrity."""

    def __init__(self, log_file_path: str = None):
        self.log_file_path = log_file_path or tempfile.mktemp(suffix='.jsonl')
        self.xai_logger = XAILogger(trace_id="xai_audit_test_123", log_file=self.log_file_path)
        self.exchange = MockExchangeFactory.create_deterministic_exchange()

    async def validate_complete_trade_flow_audit(self) -> Dict[str, Any]:
        """Validate that a complete trade flow generates proper XAI audit trail."""
        results = {
            "trade_flows_tested": 0,
            "audit_events_generated": 0,
            "required_events_present": 0,
            "event_sequence_valid": True,
            "correlation_ids_consistent": True,
            "missing_events": [],
            "sequence_errors": [],
            "correlation_errors": []
        }

        # Test multiple trade flows
        trade_scenarios = [
            {
                "name": "market_buy_complete",
                "order": OrderRequest(
                    symbol="BTCUSDT",
                    side=Side.BUY,
                    type=OrderType.MARKET,
                    quantity=1.0,
                    client_order_id="audit_test_buy_1"
                ),
                "expected_events": [
                    "ORDER.SUBMITTED",
                    "ORDER.ACCEPTED",
                    "ORDER.FILLED",
                    "POSITION.UPDATED",
                    "TRADE.COMPLETED"
                ]
            },
            {
                "name": "limit_sell_partial",
                "order": OrderRequest(
                    symbol="ETHUSDT",
                    side=Side.SELL,
                    type=OrderType.LIMIT,
                    quantity=2.0,
                    price=3000.0,
                    client_order_id="audit_test_sell_1"
                ),
                "expected_events": [
                    "ORDER.SUBMITTED",
                    "ORDER.ACCEPTED",
                    "ORDER.PARTIAL_FILL",
                    "POSITION.UPDATED",
                    "ORDER.FILLED",
                    "TRADE.COMPLETED"
                ]
            }
        ]

        for scenario in trade_scenarios:
            results["trade_flows_tested"] += 1

            # Clear previous events
            self._clear_log_file()

            # Execute trade flow
            flow_result = await self._execute_trade_flow_with_audit(scenario["order"])

            # Validate audit trail
            audit_validation = self._validate_audit_trail_for_flow(
                scenario["expected_events"],
                flow_result["correlation_id"]
            )

            results["audit_events_generated"] += audit_validation["events_found"]
            results["required_events_present"] += audit_validation["required_present"]

            if not audit_validation["sequence_valid"]:
                results["event_sequence_valid"] = False
                results["sequence_errors"].extend(audit_validation["sequence_errors"])

            if not audit_validation["correlation_valid"]:
                results["correlation_ids_consistent"] = False
                results["correlation_errors"].extend(audit_validation["correlation_errors"])

            results["missing_events"].extend(audit_validation["missing_events"])

        return results

    async def _execute_trade_flow_with_audit(self, order: OrderRequest) -> Dict[str, Any]:
        """Execute a trade flow while ensuring XAI audit logging."""
        correlation_id = f"audit_flow_{int(time.time() * 1000)}"

        # Log trade initiation
        self.xai_logger.emit("TRADE.FLOW.STARTED", {
            "correlation_id": correlation_id,
            "order_symbol": order.symbol,
            "order_side": order.side.value,
            "order_quantity": order.quantity,
            "timestamp": time.time()
        })

        # Submit order
        submit_result = await self.exchange.submit_order(order)

        # Log order submission
        self.xai_logger.emit("ORDER.SUBMITTED", {
            "correlation_id": correlation_id,
            "order_id": submit_result.get("order_id"),
            "client_order_id": order.client_order_id,
            "symbol": order.symbol,
            "side": order.side.value,
            "type": order.type.value,
            "quantity": order.quantity,
            "timestamp": time.time()
        })

        # Simulate fills
        if submit_result["status"] == "accepted":
            fills = await self.exchange.get_order_fills(submit_result["order_id"])

            for fill in fills:
                self.xai_logger.emit("ORDER.FILLED", {
                    "correlation_id": correlation_id,
                    "order_id": submit_result["order_id"],
                    "fill_id": fill.get("fill_id"),
                    "fill_quantity": fill.get("quantity"),
                    "fill_price": fill.get("price"),
                    "timestamp": time.time()
                })

        # Log trade completion
        self.xai_logger.emit("TRADE.FLOW.COMPLETED", {
            "correlation_id": correlation_id,
            "order_id": submit_result.get("order_id"),
            "final_status": submit_result.get("status"),
            "timestamp": time.time()
        })

        return {
            "correlation_id": correlation_id,
            "order_result": submit_result
        }

    def _validate_audit_trail_for_flow(self, expected_events: List[str],
                                     correlation_id: str) -> Dict[str, Any]:
        """Validate audit trail for a specific trade flow."""
        validation = {
            "events_found": 0,
            "required_present": 0,
            "sequence_valid": True,
            "correlation_valid": True,
            "missing_events": [],
            "sequence_errors": [],
            "correlation_errors": []
        }

        # Read audit events from log file
        events = self._read_audit_events()

        # Filter events by correlation ID
        flow_events = [e for e in events if e.get("correlation_id") == correlation_id]

        validation["events_found"] = len(flow_events)

        # Check for required events
        found_event_types = {e["type"] for e in flow_events}

        for expected_event in expected_events:
            if expected_event in found_event_types:
                validation["required_present"] += 1
            else:
                validation["missing_events"].append(expected_event)

        # Validate event sequence
        event_sequence = [e["type"] for e in flow_events]
        sequence_validation = self._validate_event_sequence(event_sequence, expected_events)

        validation["sequence_valid"] = sequence_validation["valid"]
        validation["sequence_errors"] = sequence_validation["errors"]

        # Validate correlation ID consistency
        correlation_validation = self._validate_correlation_consistency(flow_events, correlation_id)

        validation["correlation_valid"] = correlation_validation["valid"]
        validation["correlation_errors"] = correlation_validation["errors"]

        return validation

    def _validate_event_sequence(self, actual_sequence: List[str],
                               expected_sequence: List[str]) -> Dict[str, Any]:
        """Validate that events occur in the correct sequence."""
        validation = {
            "valid": True,
            "errors": []
        }

        # Create position mapping for expected events
        expected_positions = {}
        for i, event_type in enumerate(expected_sequence):
            if event_type not in expected_positions:
                expected_positions[event_type] = []
            expected_positions[event_type].append(i)

        # Check sequence constraints
        last_position = -1
        for event_type in actual_sequence:
            if event_type in expected_positions:
                # Find the earliest possible position for this event type
                possible_positions = expected_positions[event_type]
                valid_position = None

                for pos in possible_positions:
                    if pos >= last_position:
                        valid_position = pos
                        break

                if valid_position is None:
                    validation["valid"] = False
                    validation["errors"].append(
                        f"Event {event_type} occurred out of sequence"
                    )
                else:
                    last_position = valid_position

        return validation

    def _validate_correlation_consistency(self, events: List[Dict[str, Any]],
                                        expected_correlation_id: str) -> Dict[str, Any]:
        """Validate that all events have consistent correlation IDs."""
        validation = {
            "valid": True,
            "errors": []
        }

        for event in events:
            event_correlation_id = event.get("correlation_id")
            if event_correlation_id != expected_correlation_id:
                validation["valid"] = False
                validation["errors"].append(
                    f"Event {event['type']} has inconsistent correlation_id: "
                    f"{event_correlation_id} != {expected_correlation_id}"
                )

        return validation

    def _read_audit_events(self) -> List[Dict[str, Any]]:
        """Read audit events from log file."""
        events = []

        if not os.path.exists(self.log_file_path):
            return events

        try:
            with open(self.log_file_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            event = json.loads(line)
                            events.append(event)
                        except json.JSONDecodeError:
                            continue  # Skip malformed lines
        except Exception:
            pass  # Return empty list if file can't be read

        return events

    def _clear_log_file(self):
        """Clear the log file for fresh testing."""
        try:
            if os.path.exists(self.log_file_path):
                os.remove(self.log_file_path)
        except Exception:
            pass

    async def validate_audit_performance_impact(self) -> Dict[str, Any]:
        """Validate that audit logging doesn't significantly impact performance."""
        results = {
            "baseline_measurements": 0,
            "audit_measurements": 0,
            "baseline_avg_latency": 0.0,
            "audit_avg_latency": 0.0,
            "performance_impact_percent": 0.0,
            "within_acceptable_limit": True
        }

        # Measure baseline performance (without audit)
        baseline_latencies = []
        for i in range(50):
            order = OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"baseline_{i}"
            )

            start_time = time.time()
            await self.exchange.submit_order(order)
            end_time = time.time()

            baseline_latencies.append(end_time - start_time)

        results["baseline_measurements"] = len(baseline_latencies)
        results["baseline_avg_latency"] = sum(baseline_latencies) / len(baseline_latencies)

        # Measure performance with audit enabled
        audit_latencies = []
        for i in range(50):
            order = OrderRequest(
                symbol="ETHUSDT",
                side=Side.SELL,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"audit_perf_{i}"
            )

            start_time = time.time()
            await self._execute_trade_flow_with_audit(order)
            end_time = time.time()

            audit_latencies.append(end_time - start_time)

        results["audit_measurements"] = len(audit_latencies)
        results["audit_avg_latency"] = sum(audit_latencies) / len(audit_latencies)

        # Calculate performance impact
        if results["baseline_avg_latency"] > 0:
            impact = ((results["audit_avg_latency"] - results["baseline_avg_latency"]) /
                     results["baseline_avg_latency"]) * 100
            results["performance_impact_percent"] = impact

            # Acceptable impact limit (e.g., 50% increase is acceptable)
            results["within_acceptable_limit"] = impact < 50.0

        return results

    async def validate_audit_event_structure(self) -> Dict[str, Any]:
        """Validate that audit events have required structure and fields."""
        results = {
            "events_tested": 0,
            "events_valid": 0,
            "structure_errors": [],
            "missing_fields": [],
            "invalid_types": []
        }

        # Generate some test events
        test_order = OrderRequest(
            symbol="ADAUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
            client_order_id="structure_test_1"
        )

        await self._execute_trade_flow_with_audit(test_order)

        # Read and validate events
        events = self._read_audit_events()

        required_fields = {
            "type": str,
            "timestamp": (int, float),
            "correlation_id": str
        }

        for event in events:
            results["events_tested"] += 1

            event_valid = True

            # Check required fields
            for field_name, expected_type in required_fields.items():
                if field_name not in event:
                    results["missing_fields"].append(f"{event.get('type', 'unknown')}: missing {field_name}")
                    event_valid = False
                elif not isinstance(event[field_name], expected_type):
                    results["invalid_types"].append(
                        f"{event.get('type', 'unknown')}: {field_name} has wrong type "
                        f"{type(event[field_name]).__name__} != {expected_type.__name__}"
                    )
                    event_valid = False

            # Check timestamp is reasonable
            if "timestamp" in event:
                timestamp = event["timestamp"]
                current_time = time.time()
                if not (current_time - 3600 < timestamp < current_time + 60):  # Within last hour + 1 min tolerance
                    results["structure_errors"].append(
                        f"{event.get('type', 'unknown')}: timestamp {timestamp} is unreasonable"
                    )
                    event_valid = False

            if event_valid:
                results["events_valid"] += 1

        return results


class TestXAIAuditTrail:
    """Test XAI audit trail completeness and integrity."""

    @pytest.fixture
    async def setup_audit_validator(self):
        """Setup XAI audit trail validator."""
        validator = XAIAuditTrailValidator()
        yield validator
        # Cleanup
        validator._clear_log_file()

    @pytest.mark.asyncio
    async def test_complete_trade_flow_audit(self, setup_audit_validator):
        """Test that complete trade flows generate proper XAI audit trails."""
        validator = await setup_audit_validator

        result = await validator.validate_complete_trade_flow_audit()

        # Assert audit trail completeness
        assert result["trade_flows_tested"] > 0
        assert result["audit_events_generated"] > 0
        assert result["required_events_present"] > 0
        assert result["event_sequence_valid"]
        assert result["correlation_ids_consistent"]

        print(f"Trade flow audit - Flows: {result['trade_flows_tested']}, Events: {result['audit_events_generated']}, Required: {result['required_events_present']}")

    @pytest.mark.asyncio
    async def test_audit_performance_impact(self, setup_audit_validator):
        """Test that audit logging doesn't significantly impact performance."""
        validator = await setup_audit_validator

        result = await validator.validate_audit_performance_impact()

        # Assert acceptable performance impact
        assert result["baseline_measurements"] > 0
        assert result["audit_measurements"] > 0
        assert result["within_acceptable_limit"]

        print(f"Audit performance - Baseline: {result['baseline_avg_latency']:.4f}s, With audit: {result['audit_avg_latency']:.4f}s, Impact: {result['performance_impact_percent']:.1f}%")

    @pytest.mark.asyncio
    async def test_audit_event_structure(self, setup_audit_validator):
        """Test that audit events have proper structure and required fields."""
        validator = await setup_audit_validator

        result = await validator.validate_audit_event_structure()

        # Assert event structure validity
        assert result["events_tested"] > 0
        assert result["events_valid"] == result["events_tested"]  # All events should be valid
        assert len(result["structure_errors"]) == 0
        assert len(result["missing_fields"]) == 0
        assert len(result["invalid_types"]) == 0

        print(f"Event structure - Tested: {result['events_tested']}, Valid: {result['events_valid']}")

    @pytest.mark.asyncio
    async def test_audit_trail_correlation(self, setup_audit_validator):
        """Test audit trail correlation across trade flow components."""
        validator = await setup_audit_validator

        # Execute a trade flow
        order = OrderRequest(
            symbol="SOLUSDT",
            side=Side.BUY,
            type=OrderType.MARKET,
            quantity=1.0,
            client_order_id="correlation_test_1"
        )

        flow_result = await validator._execute_trade_flow_with_audit(order)

        # Read audit events
        events = validator._read_audit_events()

        # Filter by correlation ID
        correlated_events = [e for e in events if e.get("correlation_id") == flow_result["correlation_id"]]

        # Assert correlation
        assert len(correlated_events) > 0

        # All events should have the same correlation ID
        correlation_ids = {e.get("correlation_id") for e in correlated_events}
        assert len(correlation_ids) == 1
        assert flow_result["correlation_id"] in correlation_ids

        print(f"Correlation test - Events correlated: {len(correlated_events)}, Unique correlation IDs: {len(correlation_ids)}")

    @pytest.mark.asyncio
    async def test_audit_event_sequence(self, setup_audit_validator):
        """Test that audit events occur in the correct sequence."""
        validator = await setup_audit_validator

        # Execute a trade flow
        order = OrderRequest(
            symbol="DOTUSDT",
            side=Side.SELL,
            type=OrderType.LIMIT,
            quantity=10.0,
            price=5.0,
            client_order_id="sequence_test_1"
        )

        await validator._execute_trade_flow_with_audit(order)

        # Read events and check sequence
        events = validator._read_audit_events()
        event_types = [e["type"] for e in events if "correlation_id" in e]

        # Assert logical sequence
        assert "TRADE.FLOW.STARTED" in event_types
        assert "ORDER.SUBMITTED" in event_types
        assert "TRADE.FLOW.COMPLETED" in event_types

        # Check that STARTED comes before COMPLETED
        started_idx = event_types.index("TRADE.FLOW.STARTED")
        completed_idx = event_types.index("TRADE.FLOW.COMPLETED")
        assert started_idx < completed_idx

        print(f"Event sequence - Total events: {len(event_types)}, Sequence valid: STARTED before COMPLETED")

    @pytest.mark.asyncio
    async def test_audit_trail_integrity_under_load(self, setup_audit_validator):
        """Test audit trail integrity under concurrent load."""
        validator = await setup_audit_validator

        # Execute multiple concurrent trade flows
        async def execute_flow(i: int):
            order = OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"load_test_{i}"
            )
            return await validator._execute_trade_flow_with_audit(order)

        # Run 10 concurrent flows
        tasks = [execute_flow(i) for i in range(10)]
        results = await asyncio.gather(*tasks)

        # Read all audit events
        events = validator._read_audit_events()

        # Assert all flows are properly audited
        correlation_ids = {r["correlation_id"] for r in results}
        audited_correlation_ids = {e.get("correlation_id") for e in events if "correlation_id" in e}

        # All correlation IDs should be present in audit trail
        assert correlation_ids.issubset(audited_correlation_ids)

        print(f"Load integrity - Flows executed: {len(results)}, Unique correlation IDs: {len(correlation_ids)}, Audited: {len(audited_correlation_ids)}")


# Standalone function for CI XAI audit validation
def test_xai_audit_completeness():
    """Standalone XAI audit test for CI pipeline."""
    import asyncio

    async def run_test():
        validator = XAIAuditTrailValidator()

        # Run comprehensive audit validation
        flow_result = await validator.validate_complete_trade_flow_audit()
        perf_result = await validator.validate_audit_performance_impact()
        struct_result = await validator.validate_audit_event_structure()

        # Print results for CI
        print(f"XAI Audit Test Results:")
        print(f"- Trade flows tested: {flow_result['trade_flows_tested']}")
        print(f"- Audit events generated: {flow_result['audit_events_generated']}")
        print(f"- Required events present: {flow_result['required_events_present']}")
        print(f"- Performance impact: {perf_result['performance_impact_percent']:.1f}%")
        print(f"- Events with valid structure: {struct_result['events_valid']}/{struct_result['events_tested']}")

        # Assert minimum audit quality thresholds
        assert flow_result["trade_flows_tested"] > 0
        assert flow_result["audit_events_generated"] > 0
        assert flow_result["required_events_present"] > 0
        assert flow_result["event_sequence_valid"]
        assert flow_result["correlation_ids_consistent"]
        assert perf_result["within_acceptable_limit"]
        assert struct_result["events_valid"] == struct_result["events_tested"]

        return {
            "flows_tested": flow_result["trade_flows_tested"],
            "events_generated": flow_result["audit_events_generated"],
            "required_present": flow_result["required_events_present"],
            "sequence_valid": flow_result["event_sequence_valid"],
            "correlation_valid": flow_result["correlation_ids_consistent"],
            "performance_impact": perf_result["performance_impact_percent"],
            "structure_valid": struct_result["events_valid"] == struct_result["events_tested"]
        }

    # Run the async test
    return asyncio.run(run_test())


if __name__ == "__main__":
    # Allow running standalone for manual testing
    result = test_xai_audit_completeness()
    print("XAI audit tests completed successfully!")