#!/usr/bin/env python3
"""Check gzipped rotation parts: ensure last line JSON parses and contains ISO-8601Z in 'ts_iso' if present."""
import gzip
import json
from pathlib import Path

LOG_DIR = Path('logs')
base = LOG_DIR / 'test_events.jsonl'
parts = sorted([p for p in LOG_DIR.glob('test_events.jsonl.*.jsonl.gz')])
print('found_gz=', len(parts))
for p in parts[:5]:
    try:
        with gzip.open(p, 'rb') as f:
            data = f.read().splitlines()
            if not data:
                print('EMPTY:', p.name)
                continue
            last = data[-1].decode('utf-8')
            obj = json.loads(last)
            # check ts_iso in details if present
            details = obj.get('details', {})
            ts_iso = details.get('ts_iso')
            if ts_iso and not ts_iso.endswith('Z'):
                print('BAD_TS:', p.name, ts_iso)
            else:
                print('OK:', p.name)
    except Exception as e:
        print('ERR:', p.name, e)
