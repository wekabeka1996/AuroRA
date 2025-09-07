#!/usr/bin/env python3
"""
P3-D Production Hardening Tests
Тести для перевірки resilience і production-ready функціональності.
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
def temp_session_with_logs():
    """Create session directory with continuous log generation."""
    with tempfile.TemporaryDirectory() as temp_dir:
        session_dir = Path(temp_dir) / "test_session"
        session_dir.mkdir()
        
        # Create initial log file
        log_file = session_dir / "aurora_events.jsonl"
        
        def write_test_events():
            """Write test events continuously."""
            event_id = 1
            while hasattr(write_test_events, 'running'):
                try:
                    with log_file.open("a") as f:
                        event = {
                            "timestamp": time.time(),
                            "event_code": "ORDER.SUBMITTED",
                            "details": {"order_id": f"test_{event_id:04d}"}
                        }
                        f.write(json.dumps(event) + "\n")
                        f.flush()
                    event_id += 1
                    time.sleep(0.1)  # 10 events per second
                except:
                    break
        
        # Start event generator
        write_test_events.running = True
        generator_thread = threading.Thread(target=write_test_events, daemon=True)
        generator_thread.start()
        
        yield session_dir
        
        # Stop generator
        write_test_events.running = False

class TestP3DHardening:
    """Production hardening tests."""
    
    def test_malformed_json_handling(self, temp_session_with_logs):
        """Test handling of malformed JSON lines."""
        import importlib.util
        
        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)
        
        # Create aggregator and tailer
        aggregator = live_feed.LiveAggregator(300)
        tailer = live_feed.JSONLTailer(temp_session_with_logs, aggregator)
        
        # Add malformed JSON to log file
        log_file = temp_session_with_logs / "aurora_events.jsonl"
        with log_file.open("a") as f:
            f.write('{"valid": "json"}\n')
            f.write('{invalid json}\n')  # Malformed
            f.write('{"another": "valid"}\n')
            f.write('not json at all\n')  # Malformed
            f.write('{"final": "valid"}\n')
        
        # Process file
        import asyncio
        async def test_processing():
            await tailer._tail_file("aurora_events.jsonl")
        
        asyncio.run(test_processing())
        
        # Check stats
        stats = tailer.get_stats()
        assert stats['malformed_lines'] >= 2  # At least 2 malformed lines
        assert stats['total_lines_processed'] >= 5  # All lines processed
        
    def test_oversized_line_protection(self, temp_session_with_logs):
        """Test protection against oversized lines."""
        import importlib.util
        
        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)
        
        # Create aggregator and tailer
        aggregator = live_feed.LiveAggregator(300)
        tailer = live_feed.JSONLTailer(temp_session_with_logs, aggregator)
        
        # Add oversized line
        log_file = temp_session_with_logs / "aurora_events.jsonl"
        with log_file.open("a") as f:
            # Normal line
            f.write('{"normal": "event"}\n')
            # Oversized line (> 1MB)
            huge_data = "x" * (1024 * 1024 + 100)  # 1MB + 100 bytes
            f.write(f'{{"huge": "{huge_data}"}}\n')
            # Another normal line
            f.write('{"another": "normal"}\n')
        
        # Process file
        import asyncio
        async def test_processing():
            await tailer._tail_file("aurora_events.jsonl")
        
        asyncio.run(test_processing())
        
        # Check stats
        stats = tailer.get_stats()
        assert stats['oversized_lines'] >= 1  # Oversized line detected
        
    def test_file_rotation_handling(self, temp_session_with_logs):
        """Test file rotation handling."""
        import importlib.util

        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)

        # Create aggregator and tailer
        aggregator = live_feed.LiveAggregator(window_minutes=5)
        tailer = live_feed.JSONLTailer(temp_session_with_logs, aggregator)

        log_file = temp_session_with_logs / "aurora_events.jsonl"

        # Write initial longer content to ensure different size
        initial_content = '{"initial": "content with more data to make it longer"}\n'
        with log_file.open("w") as f:
            f.write(initial_content)

        # Process file first time
        import asyncio
        async def process_once():
            await tailer._tail_file("aurora_events.jsonl")

        asyncio.run(process_once())

        # Check initial position
        initial_pos = tailer.file_positions.get("aurora_events.jsonl", 0)
        assert initial_pos > 0

        # Simulate file rotation with shorter content
        rotated_content = '{"rotated": "short"}\n'
        with log_file.open("w") as f:  # This truncates the file
            f.write(rotated_content)

        # Process again - should detect rotation
        asyncio.run(process_once())

        # Position should be reset due to smaller file size
        new_pos = tailer.file_positions.get("aurora_events.jsonl", 0)
        assert new_pos < initial_pos  # Position was reset due to rotation    def test_server_health_endpoints(self, temp_session_with_logs):
        """Test health and healthz endpoints."""
        import importlib.util

        # Import live_feed module
        live_feed_path = Path(__file__).parent.parent.parent / "tools" / "live_feed.py"
        spec = importlib.util.spec_from_file_location("live_feed", live_feed_path)
        live_feed = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(live_feed)

        # Create server components
        server = live_feed.LiveFeedServer(temp_session_with_logs, 8003)

        # Test health endpoint response structure
        import asyncio
        from unittest.mock import Mock

        async def test_endpoints():
            # Mock request
            request = Mock()

            # Test health endpoint
            response = await server.health_endpoint(request)
            health_data = json.loads(response.body.decode())
    
            # Check for actual fields returned by health endpoint
            required_fields = [
                'status', 'session_dir', 'uptime_seconds',
                'sse_clients', 'tailer_stats', 'current_metrics'
            ]
    
            for field in required_fields:
                assert field in health_data, f"Missing field: {field}"

            # Test tailer_stats structure
            tailer_stats = health_data['tailer_stats']
            assert 'files_monitored' in tailer_stats
            assert 'total_lines_processed' in tailer_stats
            assert 'malformed_lines' in tailer_stats
            assert 'oversized_lines' in tailer_stats

            # Test healthz endpoint
            healthz_response = await server.healthz_endpoint(request)
            healthz_data = json.loads(healthz_response.body.decode())
    
            assert healthz_data['status'] == 'ok'

        asyncio.run(test_endpoints())

if __name__ == "__main__":
    pytest.main([__file__, "-v"])