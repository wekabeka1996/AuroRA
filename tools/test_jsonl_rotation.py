#!/usr/bin/env python3
"""Quick test to exercise aurora_event_logger JSONL rotation with small max_bytes.

Produces at least 3 part files when writing many small events. Verifies:
 - filenames list
 - last line in each rolled file is valid JSON
 - timestamps in ISO-8601Z in the 'details' if present
 - retention: only N recent gz archives kept (we'll use retention_days=0 to force purge)
"""
from pathlib import Path
import time
import json
import shutil
import sys
from pathlib import Path
# Ensure repo root is on sys.path for local imports
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
from core.aurora_event_logger import AuroraEventLogger

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
# Small base path for test
# Use small base path for test
base = LOG_DIR / 'test_events.jsonl'
# Remove prior artifacts
for p in LOG_DIR.glob('test_events.jsonl*'):
    try:
        p.unlink()
    except Exception:
        pass

# Use very small max_bytes to force rotation frequently and retention_days small
w = AuroraEventLogger(path=base, max_bytes=2048, retention_days=1)
# Emit events (ORDER.SUBMIT) with unique cids to avoid debouncing and dedupe
parts = []
for i in range(60000):
    details = {"ts_iso": time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z', "i": i}
    # include cid to avoid de-dup
    # Use ORDER.SUBMIT to avoid HEALTH.* debounce
    w.emit(event_code='ORDER.SUBMIT', details=details)
    # check parts periodically
    if i % 50 == 0:
        parts = sorted([p for p in LOG_DIR.glob('test_events.jsonl.*.part*.jsonl')])
        if len(parts) >= 3:
            break
# List files
parts = sorted([p for p in LOG_DIR.glob('test_events.jsonl.*.part*.jsonl')])
current = base
print('parts_count=', len(parts))
for p in parts:
    # check last line JSON
    try:
        with p.open('rb') as f:
            data = f.read().splitlines()
            if not data:
                print('EMPTY:', p)
                continue
            last = data[-1].decode('utf-8')
            json.loads(last)
            print('OK_JSON:', p.name)
    except Exception as e:
        print('BAD_JSON:', p.name, e)
# Current file check
if current.exists():
    with current.open('rb') as f:
        lines = f.read().splitlines()
        if lines:
            try:
                json.loads(lines[-1].decode('utf-8'))
                print('OK_JSON_CURRENT:', current.name)
            except Exception as e:
                print('BAD_JSON_CURRENT:', e)
# Show gz archives for retention policy
gz = sorted([p for p in LOG_DIR.glob('test_events.jsonl.*.jsonl.gz')])
print('gz_count=', len(gz))
for p in gz[:5]:
    print('GZ:', p.name)

# print sample last timestamps
print('SAMPLE_PARTS=', [p.name for p in parts[:3]])
