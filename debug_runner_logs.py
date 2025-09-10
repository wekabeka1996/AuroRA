#!/usr/bin/env python3
"""
Debug script to check runner logs
"""
import json
from pathlib import Path
import tempfile

from tests.integration.test_runner_observability import _run_runner_with_mocks


def _read_jsonl(path):
    """Read JSONL file and return list of parsed records"""
    if not path.exists():
        return []
    return [json.loads(line.strip()) for line in path.read_text(encoding="utf-8").strip().split("\n") if line.strip()]

def main():
    # Create temp directory
    tmp_path = Path(tempfile.mkdtemp())
    print(f"Running runner in: {tmp_path}")

    # Run runner with mocks
    try:
        _run_runner_with_mocks(str(tmp_path), allow_gate=True, fail_exchange=False)
        print("Runner completed successfully")
    except Exception as e:
        print(f"Runner failed: {e}")
        return

    # Check files created
    files = list(tmp_path.glob("*.jsonl"))
    print(f"Files created: {[f.name for f in files]}")

    # Check orders_success.jsonl
    success_file = tmp_path / "orders_success.jsonl"
    if success_file.exists():
        success = _read_jsonl(success_file)
        print(f"orders_success.jsonl has {len(success)} records:")
        for i, rec in enumerate(success):
            print(f"  Record {i}: {rec}")
    else:
        print("orders_success.jsonl not found")

    # Check aurora_events.jsonl
    events_file = tmp_path / "aurora_events.jsonl"
    if events_file.exists():
        events = _read_jsonl(events_file)
        order_events = [ev for ev in events if "ORDER" in ev.get("event_code", "")]
        print(f"aurora_events.jsonl has {len(order_events)} ORDER events:")
        for i, ev in enumerate(order_events):
            print(f"  Event {i}: {ev}")
    else:
        print("aurora_events.jsonl not found")

if __name__ == "__main__":
    main()
