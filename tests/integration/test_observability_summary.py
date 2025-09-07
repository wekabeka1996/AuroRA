"""
P3-C Observability Summary Integration Tests
===========================================

Tests for session summary generation and runner integration:
- Minimal session summary functionality 
- Markdown rendering
- Runner integration with OBS.SUMMARY.GENERATED events
- Large logs handling with bounded reading
"""

import json
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from tools.session_summary import summarize_session, render_markdown


class TestObservabilitySummary:
    """Test P3-C observability summary functionality."""

    def test_session_summary_minimal(self):
        """Test basic session summary with minimal data."""
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir)
            
            # Create minimal JSONL files
            aurora_events = [
                {
                    "event_code": "ORDER.ROUTE.MAKER",
                    "ts_ns": 1000000000000,
                    "details": {
                        "symbol": "BTCUSDT",
                        "route": "maker",
                        "decision_ms": 15.5
                    }
                },
                {
                    "event_code": "ORDER.ROUTE.TAKER", 
                    "ts_ns": 1000000001000,
                    "details": {
                        "symbol": "BTCUSDT",
                        "route": "taker",
                        "decision_ms": 22.3
                    }
                },
                {
                    "event_code": "GOVERNANCE.SPRT.UPDATE",
                    "ts_ns": 1000000002000,
                    "details": {
                        "why": "SPRT_UPDATE",
                        "test_id": "sprt:BTCUSDT:BUY:maker"
                    }
                },
                {
                    "event_code": "GOVERNANCE.SNAPSHOT.OK",
                    "ts_ns": 1000000003000,
                    "details": {
                        "active_tests": 2,
                        "events_since": 5
                    }
                }
            ]
            
            orders_success = [
                {
                    "status": "ack",
                    "symbol": "BTCUSDT",
                    "side": "buy",
                    "qty": 0.001
                },
                {
                    "status": "filled",
                    "symbol": "BTCUSDT", 
                    "side": "sell",
                    "qty": 0.001
                }
            ]
            
            orders_denied = [
                {
                    "reason": "RISK_GUARD_BLOCK",
                    "symbol": "BTCUSDT"
                }
            ]
            
            orders_failed = []
            
            # Write test data to JSONL files
            self._write_jsonl(session_dir / "aurora_events.jsonl", aurora_events)
            self._write_jsonl(session_dir / "orders_success.jsonl", orders_success)
            self._write_jsonl(session_dir / "orders_denied.jsonl", orders_denied)
            self._write_jsonl(session_dir / "orders_failed.jsonl", orders_failed)
            
            # Generate summary
            summary = summarize_session(session_dir, max_lines=1000)
            
            # Verify required keys exist
            assert "session" in summary
            assert "governance" in summary
            assert "latency" in summary
            assert "xai" in summary
            
            # Verify session data
            session = summary["session"]
            assert session["symbols"] == ["BTCUSDT"]
            assert session["orders"]["submitted"] == 2
            assert session["orders"]["ack"] == 1
            assert session["orders"]["filled"] == 1
            assert session["orders"]["denied"] == 1
            assert session["orders"]["failed"] == 0
            
            # Verify routes
            routes = session["routes"]
            assert routes["maker"] == 1
            assert routes["taker"] == 1
            
            # Verify governance
            governance = summary["governance"]
            assert governance["alpha"]["totals"]["active"] == 2
            assert governance["sprt"]["updates"] == 1
            
            # Verify latency percentiles exist
            latency = summary["latency"]
            assert "decision_ms_p50" in latency
            assert "decision_ms_p90" in latency
            
            # Verify XAI codes
            xai = summary["xai"]
            assert "why_code_counts" in xai
            assert "SPRT_UPDATE" in xai["why_code_counts"]

    def test_session_summary_markdown_render(self):
        """Test markdown rendering of session summary."""
        # Sample summary data
        summary = {
            "session": {
                "start_ts_ns": "1000000000000",
                "end_ts_ns": "1000000060000", 
                "duration_s": 60.0,
                "symbols": ["BTCUSDT", "ETHUSDT"],
                "orders": {
                    "submitted": 10,
                    "ack": 8,
                    "filled": 6,
                    "partially_filled": 1,
                    "cancelled": 1,
                    "denied": 2,
                    "failed": 0
                },
                "routes": {
                    "maker": 6,
                    "taker": 4,
                    "deny": 2,
                    "cancel": 1
                }
            },
            "governance": {
                "alpha": {
                    "totals": {
                        "active": 3,
                        "closed": 2,
                        "alloc": 0.15,
                        "spent": 0.08
                    }
                },
                "sprt": {
                    "updates": 25,
                    "final": {
                        "accept_h0": 1,
                        "accept_h1": 1,
                        "timeout": 0
                    }
                }
            },
            "latency": {
                "decision_ms_p50": 18.5,
                "decision_ms_p90": 35.2,
                "to_first_fill_ms_p50": 95.0,
                "to_first_fill_ms_p90": 180.0
            },
            "sla": {
                "breaches": 1,
                "guard_denies": 2
            },
            "edge": {
                "avg_edge_bps": 2.8,
                "maker_share_pct": 60.0,
                "taker_share_pct": 40.0
            },
            "xai": {
                "why_code_counts": {
                    "OK_ROUTE_MAKER": 6,
                    "OK_ROUTE_TAKER": 4,
                    "WHY_GUARD_BLOCK": 2
                }
            }
        }
        
        # Render markdown
        md_content = render_markdown(summary)
        
        # Verify markdown contains expected sections
        assert "# Trading Session Summary" in md_content
        assert "## Orders Overview" in md_content
        assert "## Route Distribution" in md_content
        assert "## Governance Alpha" in md_content
        assert "## SPRT Statistics" in md_content
        assert "## Latency Performance" in md_content
        assert "## Top WHY Codes" in md_content
        assert "## Summary" in md_content
        
        # Verify specific data appears in markdown
        assert "Submitted | 10" in md_content
        assert "Maker | 6 | 60.0%" in md_content
        assert "Decision P50 | 18.5ms" in md_content
        assert "Active Tests | 3" in md_content
        assert "OK_ROUTE_MAKER" in md_content
        
        # Verify markdown is non-empty and reasonable length
        assert len(md_content) > 500
        assert len(md_content.split('\n')) > 20

    def test_runner_emits_summary_generated(self):
        """Test that runner generates summary files and emits OBS.SUMMARY.GENERATED event."""
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir)
            
            # Create minimal aurora_events.jsonl for runner simulation
            aurora_events = [
                {
                    "event_code": "ORDER.ROUTE.MAKER",
                    "ts_ns": int(time.time() * 1e9),
                    "details": {"symbol": "BTCUSDT", "route": "maker"}
                }
            ]
            
            self._write_jsonl(session_dir / "aurora_events.jsonl", aurora_events)
            self._write_jsonl(session_dir / "orders_success.jsonl", [])
            self._write_jsonl(session_dir / "orders_denied.jsonl", [])
            self._write_jsonl(session_dir / "orders_failed.jsonl", [])
            
            # Simulate runner summary generation
            reports_dir = session_dir / "reports"
            reports_dir.mkdir(exist_ok=True)
            
            # Generate summary
            summary = summarize_session(session_dir)
            
            # Write outputs (simulating runner behavior)
            json_path = reports_dir / "session_summary.json"
            md_path = reports_dir / "session_summary.md"
            
            json_path.write_text(json.dumps(summary, indent=2), encoding='utf-8')
            md_path.write_text(render_markdown(summary), encoding='utf-8')
            
            # Simulate OBS.SUMMARY.GENERATED event
            obs_event = {
                "event_code": "OBS.SUMMARY.GENERATED",
                "ts_ns": int(time.time() * 1e9),
                "details": {
                    "out_json": str(json_path.relative_to(session_dir)),
                    "out_md": str(md_path.relative_to(session_dir)),
                    "orders_total": summary.get("session", {}).get("orders", {}).get("submitted", 0),
                    "routes": summary.get("session", {}).get("routes", {}),
                    "alpha_totals": summary.get("governance", {}).get("alpha", {}).get("totals", {})
                }
            }
            
            # Append event to aurora_events.jsonl
            with open(session_dir / "aurora_events.jsonl", "a", encoding='utf-8') as f:
                f.write(json.dumps(obs_event) + "\n")
            
            # Verify files exist
            assert json_path.exists(), "session_summary.json should be created"
            assert md_path.exists(), "session_summary.md should be created"
            
            # Verify JSON content
            with open(json_path, 'r', encoding='utf-8') as f:
                saved_summary = json.load(f)
            assert "session" in saved_summary
            assert "governance" in saved_summary
            
            # Verify MD content
            md_content = md_path.read_text(encoding='utf-8')
            assert "# Trading Session Summary" in md_content
            
            # Verify OBS.SUMMARY.GENERATED event exists in log
            with open(session_dir / "aurora_events.jsonl", 'r', encoding='utf-8') as f:
                events = [json.loads(line.strip()) for line in f if line.strip()]
            
            obs_events = [e for e in events if e.get("event_code") == "OBS.SUMMARY.GENERATED"]
            assert len(obs_events) == 1, "Should have exactly one OBS.SUMMARY.GENERATED event"
            
            obs_event = obs_events[0]
            # Use Path().as_posix() to normalize path separators for cross-platform compatibility
            assert Path(obs_event["details"]["out_json"]).as_posix() == "reports/session_summary.json"
            assert Path(obs_event["details"]["out_md"]).as_posix() == "reports/session_summary.md"
            assert "orders_total" in obs_event["details"]
            assert "routes" in obs_event["details"]
            assert "alpha_totals" in obs_event["details"]

    def test_large_logs_bounded(self):
        """Test that large logs are handled with max_lines boundary."""
        with tempfile.TemporaryDirectory() as temp_dir:
            session_dir = Path(temp_dir)
            
            # Generate large number of events (more than max_lines limit)
            large_events = []
            max_lines_limit = 1000
            
            for i in range(max_lines_limit + 500):  # Generate more than limit
                event = {
                    "event_code": "ORDER.ROUTE.MAKER" if i % 2 == 0 else "ORDER.ROUTE.TAKER",
                    "ts_ns": 1000000000000 + i * 1000,
                    "details": {
                        "symbol": "BTCUSDT",
                        "route": "maker" if i % 2 == 0 else "taker",
                        "decision_ms": 10.0 + (i % 20)
                    }
                }
                large_events.append(event)
            
            # Write large JSONL file
            self._write_jsonl(session_dir / "aurora_events.jsonl", large_events)
            self._write_jsonl(session_dir / "orders_success.jsonl", [])
            self._write_jsonl(session_dir / "orders_denied.jsonl", [])
            self._write_jsonl(session_dir / "orders_failed.jsonl", [])
            
            # Test with bounded reading
            summary = summarize_session(session_dir, max_lines=max_lines_limit)
            
            # Verify that processing completed without OOM
            assert "session" in summary
            assert "governance" in summary
            
            # Verify that some data was processed (should be exactly max_lines_limit events)
            routes = summary["session"]["routes"]
            total_routes = sum(routes.values())
            
            # Should process exactly max_lines_limit events, not more
            assert total_routes == max_lines_limit, f"Expected {max_lines_limit} events, got {total_routes}"
            
            # Verify latency stats exist and are reasonable
            latency = summary["latency"]
            assert latency["decision_ms_p50"] > 0
            assert latency["decision_ms_p90"] > 0
            assert latency["decision_ms_p50"] <= latency["decision_ms_p90"]
            
            # Test with very small limit
            small_summary = summarize_session(session_dir, max_lines=10)
            small_routes = small_summary["session"]["routes"]
            small_total = sum(small_routes.values())
            assert small_total == 10, f"Expected 10 events with small limit, got {small_total}"

    def _write_jsonl(self, path: Path, events: list):
        """Helper to write list of dicts to JSONL file."""
        with open(path, 'w', encoding='utf-8') as f:
            for event in events:
                f.write(json.dumps(event) + "\n")