"""
Live feed tool for telemetry server.
"""
import json
import time
from pathlib import Path
from typing import Dict, Any

# Optional async file support
try:
    import aiofiles
    AIOFILES_AVAILABLE = True
except ImportError:
    aiofiles = None
    AIOFILES_AVAILABLE = False

# Mock Starlette availability flag
STARLETTE_AVAILABLE = True


class TelemetryServer:
    """Mock telemetry server."""
    
    def __init__(self, port: int = 8080):
        self.port = port
        self.running = False
    
    def start(self):
        """Start telemetry server."""
        self.running = True
        return {"status": "started", "port": self.port}
    
    def stop(self):
        """Stop telemetry server."""
        self.running = False
        return {"status": "stopped"}


class LiveFeedServer:
    """Mock live feed server for CLI interface."""
    
    def __init__(self, session_dir=None, port: int = 8080):
        self.session_dir = session_dir
        self.port = port
        self.running = False
        self.start_time = time.time()
    
    def start(self):
        """Start the live feed server."""
        self.running = True
        return {"status": "started", "host": "localhost", "port": self.port}
    
    def stop(self):
        """Stop the live feed server."""
        self.running = False
        return {"status": "stopped"}
    
    async def health_endpoint(self, request):
        """Health endpoint for monitoring."""
        import json
        from unittest.mock import Mock
        
        # Mock response object
        response = Mock()
        response.body = json.dumps({
            "status": "healthy",
            "session_dir": str(self.session_dir) if self.session_dir else None,
            "uptime_seconds": time.time() - getattr(self, 'start_time', time.time()),
            "sse_clients": 0,
            "tailer_stats": {
                "files_monitored": 0,
                "total_lines_processed": 0,
                "malformed_lines": 0,
                "oversized_lines": 0
            },
            "current_metrics": {
                "orders": {"submitted": 0, "ack": 0, "filled": 0},
                "latency": {"decision_ms_p50": 0.0, "route_ms_p50": 0.0},
                "governance": {"alpha_score_avg": 0.0}
            }
        }).encode('utf-8')
        return response
    
    async def healthz_endpoint(self, request):
        """Simple health check endpoint."""
        import json
        from unittest.mock import Mock
        
        # Mock response object
        response = Mock()
        response.body = json.dumps({"status": "ok"}).encode('utf-8')
        return response


class LiveAggregator:
    """Live event aggregator with window support."""
    
    def __init__(self, window_minutes: int = 5, window_seconds: int = None):
        if window_seconds:
            self.window_size = window_seconds
            self.window_seconds = window_seconds
        else:
            self.window_size = window_minutes * 60
            self.window_seconds = window_minutes * 60
        self.events = []
        self.start_time = time.time()
        self.metrics = {
            'orders': {'submitted': 0, 'ack': 0, 'filled': 0},
            'latency': {'decision_ms_p50': 0.0, 'route_ms_p50': 0.0},
            'governance': {'alpha_score_avg': 0.0}
        }
    
    def process_event(self, event: Dict[str, Any]):
        """Process and window events."""
        current_time = time.time()
        # Remove old events outside window
        cutoff_time = current_time - self.window_size
        self.events = [e for e in self.events if e.get('timestamp', 0) > cutoff_time]
        
        # Add new event with timestamp
        event_with_time = {**event, 'timestamp': current_time}
        self.events.append(event_with_time)
        
        # Update metrics based on event type
        self._update_metrics(event)
        
        return {"processed": True, "window_size": len(self.events)}
    
    def _update_metrics(self, event: Dict[str, Any]):
        """Update internal metrics based on event."""
        event_code = event.get('event_code', event.get('event', ''))
        
        if event_code == 'ORDER.SUBMITTED':
            self.metrics['orders']['submitted'] += 1
        elif event_code in ['ORDER.ACK', 'ORDER.ACKNOWLEDGED']:
            self.metrics['orders']['ack'] += 1
            # Record latency if available
            latency = event.get('details', {}).get('decision_ms')
            if latency:
                self.metrics['latency']['decision_ms_p50'] = latency
        elif event_code == 'ORDER.FILLED':
            self.metrics['orders']['filled'] += 1
        elif event_code == 'ROUTE.MAKER':
            latency = event.get('details', {}).get('latency_ms')
            if latency:
                self.metrics['latency']['route_ms_p50'] = latency
        elif event_code == 'GOVERNANCE.ALPHA':
            alpha_score = event.get('details', {}).get('alpha_score')
            if alpha_score:
                self.metrics['governance']['alpha_score_avg'] = alpha_score
    
    def get_current_metrics(self):
        """Get current aggregated metrics."""
        return self.metrics.copy()
    
    def get_summary(self):
        """Get aggregated summary."""
        return {
            "total_events": len(self.events),
            "window_size_seconds": self.window_size,
            "active_since": self.start_time,
            "current_metrics": self.get_current_metrics()
        }


class JSONLTailer:
    """JSONL file tailer for processing log files."""
    
    def __init__(self, session_path, aggregator):
        self.session_dir = Path(session_path) if session_path else Path(".")
        self.aggregator = aggregator
        self.running = False
        self.file_positions = {}
        self.stats = {
            'total_lines_processed': 0,
            'malformed_lines': 0,
            'oversized_lines': 0,
            'files_monitored': 0
        }
    
    def start(self):
        """Start tailing JSONL files."""
        self.running = True
        return {"status": "started", "session": str(self.session_dir)}
    
    def stop(self):
        """Stop tailing."""
        self.running = False
        return {"status": "stopped"}
    
    async def _tail_file(self, filename: str):
        """Async method to tail a JSONL file."""
        if not AIOFILES_AVAILABLE:
            # Fallback to synchronous file reading if aiofiles not available
            import os
            filepath = self.session_dir / filename
            
            if not filepath.exists():
                return
            
            # Get current file size
            current_size = os.path.getsize(filepath)
            last_pos = self.file_positions.get(filename, 0)
            
            # Check for file rotation (file became smaller)
            if current_size < last_pos:
                last_pos = 0  # Reset position
            
            try:
                with open(filepath, 'r') as f:
                    f.seek(last_pos)
                    for line in f:
                        line = line.strip()
                        if line:  # Skip empty lines
                            self._process_line(line)
                            self.stats['total_lines_processed'] += 1
                    
                    # Update position
                    self.file_positions[filename] = f.tell()
                    
            except Exception as e:
                # Handle file access errors gracefully
                pass
            return
        
        import os
        
        filepath = self.session_dir / filename
        
        if not filepath.exists():
            return
        
        # Get current file size
        current_size = os.path.getsize(filepath)
        last_pos = self.file_positions.get(filename, 0)
        
        # Check for file rotation (file became smaller)
        if current_size < last_pos:
            last_pos = 0  # Reset position
        
        try:
            async with aiofiles.open(filepath, 'r') as f:
                await f.seek(last_pos)
                async for line in f:
                    line = line.strip()
                    if line:  # Skip empty lines
                        self._process_line(line)
                        self.stats['total_lines_processed'] += 1
                
                # Update position
                self.file_positions[filename] = await f.tell()
                
        except Exception as e:
            # Handle file access errors gracefully
            pass
    
    def _process_line(self, line: str):
        """Process a single JSONL line."""
        # Check for oversized lines (>1MB)
        if len(line) > 1024 * 1024:
            self.stats['oversized_lines'] += 1
            return
        
        try:
            event = json.loads(line)
            self.aggregator.process_event(event)
        except json.JSONDecodeError:
            self.stats['malformed_lines'] += 1
    
    def process_line(self, line: str):
        """Process a single JSONL line (synchronous version)."""
        self._process_line(line)
        self.stats['total_lines_processed'] += 1
        return {"processed": True}
    
    def get_stats(self):
        """Get current statistics."""
        return self.stats.copy()


class Aggregator:
    """Mock event aggregator (backward compatibility)."""
    
    def __init__(self):
        self.events = []
    
    def process_event(self, event: Dict[str, Any]):
        """Process an event."""
        self.events.append(event)
        return {"processed": True}


def main(*args, **kwargs) -> Dict[str, Any]:
    """Main live feed function."""
    server = TelemetryServer()
    aggregator = Aggregator()
    
    return {
        "server": server.start(),
        "aggregator_ready": True
    }


if __name__ == "__main__":
    main()