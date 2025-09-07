#!/usr/bin/env python3
"""
Integration tests for P3-D Live Dashboards functionality.
Tests telemetry server, SSE endpoint, and dashboard integration.
"""

import asyncio
import json
import tempfile
import time
import threading
from pathlib import Path
import pytest
import subprocess
import sys
import os
import urllib.request
import urllib.error

@pytest.fixture
def temp_session_dir():
    """Create temporary session directory with test logs."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = Path(temp_dir) / "test_session"
        session_dir.mkdir()
        
        # Create test JSONL logs
        log_file = session_dir / "runner.jsonl"
        with log_file.open("w") as f:
            # Sample events for testing
            events = [
                {
                    "timestamp": "2024-01-01T12:00:00Z",
                    "event": "ORDER.SUBMITTED",
                    "details": {"order_id": "test_001", "symbol": "BTCUSDT", "side": "BUY", "qty": 0.1}
                },
                {
                    "timestamp": "2024-01-01T12:00:01Z", 
                    "event": "ORDER.ACKNOWLEDGED",
                    "details": {"order_id": "test_001", "exchange_id": "exch_123"}
                },
                {
                    "timestamp": "2024-01-01T12:00:02Z",
                    "event": "ORDER.FILLED", 
                    "details": {"order_id": "test_001", "fill_qty": 0.1, "fill_price": 45000}
                },
                {
                    "timestamp": "2024-01-01T12:00:03Z",
                    "event": "ROUTE.MAKER",
                    "details": {"latency_ms": 15.5, "order_id": "test_001"}
                },
                {
                    "timestamp": "2024-01-01T12:00:04Z",
                    "event": "GOVERNANCE.ALPHA",
                    "details": {"alpha_score": 0.85, "decision": "allow"}
                }
            ]
            
            for event in events:
                f.write(json.dumps(event) + "\n")
        
        yield session_dir

class TestP3DLiveFeed:
    """Test suite for P3-D live feed functionality."""
    
    def test_telemetry_server_components(self, temp_session_dir):
        """Test that telemetry server components can be instantiated."""
        import importlib.util
        
        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)
        
        # Test LiveAggregator
        aggregator = live_feed.LiveAggregator(window_seconds=300)
        assert aggregator.window_seconds == 300
        
        # Test JSONLTailer with correct parameters
        tailer = live_feed.JSONLTailer(temp_session_dir, aggregator)
        assert tailer.session_dir == temp_session_dir
        assert tailer.aggregator == aggregator
        
        # Test that we can create server (but not start it)
        server = live_feed.LiveFeedServer(temp_session_dir, 8002)
        assert server.session_dir == temp_session_dir
        assert server.port == 8002
                        
    def test_aggregator_event_processing(self, temp_session_dir):
        """Test that aggregator processes events correctly."""
        import importlib.util
        
        # Import live_feed module  
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)
        
        aggregator = live_feed.LiveAggregator(window_seconds=300)
        
        # Test order events with correct format
        order_event = {
            "timestamp": "2024-01-01T12:00:00Z",
            "event_code": "ORDER.SUBMITTED",  # Use event_code instead of event
            "details": {"order_id": "test_001"}
        }
        aggregator.process_event(order_event)
        
        metrics = aggregator.get_current_metrics()
        assert metrics['orders']['submitted'] == 1
        
        # Test route events with latency
        route_event = {
            "timestamp": "2024-01-01T12:00:01Z",
            "event_code": "ORDER.ACK",  # Use correct format 
            "details": {"decision_ms": 15.5}
        }
        aggregator.process_event(route_event)
        
        metrics = aggregator.get_current_metrics()
        assert metrics['orders']['ack'] == 1
        # Check that latency was recorded
        assert metrics['latency']['decision_ms_p50'] > 0

    def test_telemetry_server_module_imports(self):
        """Test that all required dependencies can be imported."""
        import importlib.util
        
        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)
        
        # Test Starlette availability check
        assert hasattr(live_feed, 'STARLETTE_AVAILABLE')
        
        # Test that classes are defined
        assert hasattr(live_feed, 'LiveFeedServer')
        assert hasattr(live_feed, 'LiveAggregator') 
        assert hasattr(live_feed, 'JSONLTailer')
                        
def test_runner_telemetry_integration():
    """Test that runner properly integrates with telemetry."""
    from skalp_bot.runner.run_live_aurora import main
    
    # Check that main function accepts telemetry parameter
    import inspect
    sig = inspect.signature(main)
    assert 'telemetry' in sig.parameters
    
    # Check parameter default
    assert sig.parameters['telemetry'].default is False

def test_live_feed_cli_interface():
    """Test live_feed.py CLI interface."""
    import importlib.util
    
    # Import live_feed module
    live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
    spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
    live_feed = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(live_feed)
    
    # Check main function exists
    assert hasattr(live_feed, 'main')
    
    # Check required classes exist
    assert hasattr(live_feed, 'LiveFeedServer')
    assert hasattr(live_feed, 'LiveAggregator')
    assert hasattr(live_feed, 'JSONLTailer')

def test_dashboard_launcher_exists():
    """Test that dashboard launcher exists and is executable."""
    launcher_path = Path(__file__).parent.parent.parent / "tools" / "dashboard_launcher.py"
    assert launcher_path.exists()
    
    # Check it's a valid Python file with proper encoding
    with launcher_path.open(encoding='utf-8') as f:
        content = f.read()
        assert 'def main(' in content
        assert 'dashboard' in content.lower()

if __name__ == "__main__":
    pytest.main([__file__, "-v"])