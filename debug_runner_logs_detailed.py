#!/usr/bin/env python3
"""
Enhanced debug script to check ALL logs
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
        import traceback
        traceback.print_exc()
        return

    # Check ALL files created
    all_files = list(tmp_path.glob("*"))
    print(f"All files created: {[f.name for f in all_files]}")

    # Check each JSONL file
    for jsonl_file in tmp_path.glob("*.jsonl"):
        records = _read_jsonl(jsonl_file)
        print(f"\n{jsonl_file.name} has {len(records)} records:")
        for i, rec in enumerate(records):
            print(f"  Record {i}: {rec}")

    # Check aurora_events.jsonl for ALL events
    events_file = tmp_path / "aurora_events.jsonl"
    if events_file.exists():
        events = _read_jsonl(events_file)
        print(f"\naurora_events.jsonl has {len(events)} total events:")
        for i, ev in enumerate(events):
            print(f"  Event {i}: {ev.get('event_code', 'NO_CODE')} - {ev}")

if __name__ == "__main__":
    main()
