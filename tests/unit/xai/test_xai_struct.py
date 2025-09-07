import json
import pytest
from pathlib import Path
from common.xai_logger import XAILogger


class TestXAILoggerStructure:
    """Test XAI logger event structure and required fields"""

    def test_xai_logs_have_required_fields(self, tmp_path):
        """Test that XAI logs contain all required fields"""
        log_file = tmp_path / "test_xai.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        trace_id = logger.emit(
            component="signal",
            decision="accept",
            input_={"score": 1.5, "threshold": 1.0},
            explanation={"type": "threshold_rule", "rule": "score > threshold"},
            confidence=0.85
        )

        # Read the log file
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 1
        event = json.loads(lines[0])

        # Check required fields
        required_fields = ["ts", "component", "decision", "input", "explanation", "confidence", "trace_id"]
        for field in required_fields:
            assert field in event, f"Missing required field: {field}"

        # Check field types
        assert isinstance(event["ts"], int)
        assert isinstance(event["component"], str)
        assert isinstance(event["decision"], str)
        assert isinstance(event["input"], dict)
        assert isinstance(event["explanation"], dict)
        assert isinstance(event["confidence"], float)
        assert isinstance(event["trace_id"], str)

        # Check specific values
        assert event["component"] == "signal"
        assert event["decision"] == "accept"
        assert event["input"]["score"] == 1.5
        assert event["confidence"] == 0.85
        assert event["trace_id"] == trace_id

    def test_trace_id_generation(self, tmp_path):
        """Test that trace_id is generated when not provided"""
        log_file = tmp_path / "test_trace.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        trace_id = logger.emit("test", "decision", {}, {}, 0.5)

        with open(log_file, 'r', encoding='utf-8') as f:
            event = json.loads(f.read())

        assert event["trace_id"] == trace_id
        assert len(trace_id) > 0

    def test_trace_id_propagation(self, tmp_path):
        """Test that provided trace_id is preserved"""
        log_file = tmp_path / "test_propagation.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        custom_trace_id = "custom-trace-123"
        returned_trace_id = logger.emit("test", "decision", {}, {}, 0.5, trace_id=custom_trace_id)

        with open(log_file, 'r', encoding='utf-8') as f:
            event = json.loads(f.read())

        assert event["trace_id"] == custom_trace_id
        assert returned_trace_id == custom_trace_id

    def test_multiple_events_same_trace(self, tmp_path):
        """Test multiple events with same trace_id"""
        log_file = tmp_path / "test_multiple.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        trace_id = "shared-trace-456"

        logger.emit("signal", "accept", {"score": 1.0}, {"rule": "threshold"}, 0.8, trace_id=trace_id)
        logger.emit("risk", "size", {"amount": 100}, {"method": "fixed"}, 0.9, trace_id=trace_id)
        logger.emit("oms", "sent", {"order_id": "123"}, {"exchange": "binance"}, 0.95, trace_id=trace_id)

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 3

        for line in lines:
            event = json.loads(line)
            assert event["trace_id"] == trace_id

        components = [json.loads(line)["component"] for line in lines]
        assert set(components) == {"signal", "risk", "oms"}

    def test_confidence_bounds(self, tmp_path):
        """Test confidence values are properly handled"""
        log_file = tmp_path / "test_confidence.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        # Test various confidence values
        test_cases = [0.0, 0.5, 1.0, 0.123, 0.999]

        for conf in test_cases:
            logger.emit("test", "decision", {}, {}, conf)

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        confidences = [json.loads(line)["confidence"] for line in lines]
        assert confidences == test_cases

    def test_timestamp_generation(self, tmp_path):
        """Test timestamp is reasonable"""
        log_file = tmp_path / "test_timestamp.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        before = int(time.time() * 1000)
        logger.emit("test", "decision", {}, {}, 0.5)
        after = int(time.time() * 1000)

        with open(log_file, 'r', encoding='utf-8') as f:
            event = json.loads(f.read())

        assert before <= event["ts"] <= after

    def test_thread_safety(self, tmp_path):
        """Test that logging is thread-safe"""
        import threading

        log_file = tmp_path / "test_threading.jsonl"
        logger = XAILogger(filename=log_file.name)
        logger.path = log_file

        results = []

        def log_event(i):
            trace_id = logger.emit(f"component_{i}", f"decision_{i}", {"id": i}, {"test": i}, 0.5)
            results.append(trace_id)

        threads = []
        for i in range(10):
            t = threading.Thread(target=log_event, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        assert len(lines) == 10
        assert len(results) == 10

        # All trace_ids should be unique
        trace_ids = [json.loads(line)["trace_id"] for line in lines]
        assert len(set(trace_ids)) == 10