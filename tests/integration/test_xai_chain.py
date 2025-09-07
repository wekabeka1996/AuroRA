import json
import pytest
from pathlib import Path
from common.xai_logger import xai


class TestXAIChainIntegration:
    """Integration tests for XAI logger trace_id propagation across components"""

    def test_signal_to_risk_trace_propagation(self, tmp_path):
        """Test trace_id propagation from signal to risk component"""
        # Mock signal evaluation
        def mock_signal_evaluate():
            return {
                "decision": "long",
                "confidence": 0.85,
                "trace_id": xai.emit(
                    "signal",
                    "long",
                    {"score": 1.5, "symbol": "BTCUSDT"},
                    {"type": "threshold", "threshold": 1.0, "score": 1.5},
                    0.85
                )
            }

        # Mock risk sizing
        def mock_risk_size(signal_result, trace_id):
            size = 0.1 if signal_result["decision"] == "long" else 0.0
            xai.emit(
                "risk",
                {"size": size, "action": "sized"},
                {"signal_decision": signal_result["decision"]},
                {"type": "position_sizing", "method": "fixed_pct", "size": size},
                0.9,
                trace_id=trace_id
            )
            return size

        # Redirect XAI logger to test file
        original_path = xai.path
        test_log = tmp_path / "test_chain.jsonl"
        xai.path = test_log

        try:
            # Execute the chain
            signal_result = mock_signal_evaluate()
            trace_id = signal_result["trace_id"]
            risk_size = mock_risk_size(signal_result, trace_id)

            # Verify the chain
            with open(test_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            assert len(lines) == 2

            events = [json.loads(line) for line in lines]

            # Check signal event
            signal_event = next(e for e in events if e["component"] == "signal")
            assert signal_event["decision"] == "long"
            assert signal_event["trace_id"] == trace_id

            # Check risk event
            risk_event = next(e for e in events if e["component"] == "risk")
            assert risk_event["decision"]["size"] == 0.1
            assert risk_event["trace_id"] == trace_id

        finally:
            xai.path = original_path

    def test_full_chain_signal_risk_oms(self, tmp_path):
        """Test complete chain: signal -> risk -> oms with trace_id propagation"""
        # Mock components
        def mock_signal():
            return {
                "decision": "long",
                "symbol": "BTCUSDT",
                "trace_id": xai.emit(
                    "signal",
                    "long",
                    {"score": 2.1, "symbol": "BTCUSDT"},
                    {"type": "momentum", "threshold": 2.0},
                    0.88
                )
            }

        def mock_risk(signal_result, trace_id):
            size = 0.05
            xai.emit(
                "risk",
                {"size": size, "approved": True},
                {"signal": signal_result["decision"]},
                {"type": "risk_check", "var_limit": 0.02, "passed": True},
                0.92,
                trace_id=trace_id
            )
            return {"size": size, "approved": True}

        def mock_oms(order, trace_id):
            order_id = "test_order_123"
            xai.emit(
                "oms",
                {"order_id": order_id, "status": "sent"},
                {"order": order},
                {"type": "order_routing", "exchange": "binance", "route": "spot"},
                0.95,
                trace_id=trace_id
            )
            return order_id

        # Redirect logging
        original_path = xai.path
        test_log = tmp_path / "test_full_chain.jsonl"
        xai.path = test_log

        try:
            # Execute full chain
            signal_result = mock_signal()
            trace_id = signal_result["trace_id"]

            risk_result = mock_risk(signal_result, trace_id)
            order = {
                "symbol": signal_result["symbol"],
                "side": signal_result["decision"],
                "size": risk_result["size"]
            }

            order_id = mock_oms(order, trace_id)

            # Verify complete chain
            with open(test_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            assert len(lines) == 3

            events = [json.loads(line) for line in lines]

            # Group by component
            components = {}
            for event in events:
                comp = event["component"]
                if comp not in components:
                    components[comp] = []
                components[comp].append(event)

            # Verify all components present
            assert "signal" in components
            assert "risk" in components
            assert "oms" in components

            # Verify all share same trace_id
            trace_ids = set(event["trace_id"] for event in events)
            assert len(trace_ids) == 1
            assert list(trace_ids)[0] == trace_id

            # Verify chronological order (timestamps should be non-decreasing)
            timestamps = [event["ts"] for event in events]
            assert timestamps == sorted(timestamps)

            # Verify component-specific data
            signal_event = components["signal"][0]
            assert signal_event["decision"] == "long"
            assert signal_event["input"]["symbol"] == "BTCUSDT"

            risk_event = components["risk"][0]
            assert risk_event["decision"]["approved"] == True
            assert risk_event["decision"]["size"] == 0.05

            oms_event = components["oms"][0]
            assert oms_event["decision"]["order_id"] == "test_order_123"
            assert oms_event["decision"]["status"] == "sent"

        finally:
            xai.path = original_path

    def test_trace_id_uniqueness(self, tmp_path):
        """Test that different chains have unique trace_ids"""
        original_path = xai.path
        test_log = tmp_path / "test_uniqueness.jsonl"
        xai.path = test_log

        try:
            trace_ids = []

            # Generate multiple chains
            for i in range(5):
                trace_id = xai.emit(f"component_{i}", f"decision_{i}", {"id": i}, {"test": i}, 0.5)
                trace_ids.append(trace_id)

            # Verify all trace_ids are unique
            assert len(set(trace_ids)) == len(trace_ids)

            # Verify all are in log file
            with open(test_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            logged_trace_ids = [json.loads(line)["trace_id"] for line in lines]
            assert set(logged_trace_ids) == set(trace_ids)

        finally:
            xai.path = original_path

    def test_error_conditions_trace_preservation(self, tmp_path):
        """Test that trace_id is preserved even in error conditions"""
        original_path = xai.path
        test_log = tmp_path / "test_error.jsonl"
        xai.path = test_log

        try:
            # Simulate error condition
            trace_id = "error-trace-789"

            xai.emit("signal", "error", {"error": "invalid_input"}, {"type": "validation_error"}, 0.0, trace_id=trace_id)
            xai.emit("risk", "rejected", {"reason": "signal_error"}, {"type": "cascade_rejection"}, 0.0, trace_id=trace_id)

            with open(test_log, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            assert len(lines) == 2

            for line in lines:
                event = json.loads(line)
                assert event["trace_id"] == trace_id
                assert event["confidence"] == 0.0

        finally:
            xai.path = original_path