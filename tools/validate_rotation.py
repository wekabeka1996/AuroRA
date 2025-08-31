"""Validate JSONL rotation: generate many small writes and assert retention_files enforcement.

Usage: python tools/validate_rotation.py

This script writes to logs/test_rotation.jsonl using core.order_logger._JsonlWriter with small max_bytes
and checks that at the end there are <= retention_files .jsonl.gz plus one active .jsonl.
It also verifies last line of each archive is valid JSON and has 'ts' or 'ts_ns' with Z/ISO format when present.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
import random
import sys
from pathlib import Path as _P
# Ensure repo root is on sys.path for direct script execution
ROOT = _P(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from core.order_logger import _JsonlWriter

LOG = Path('logs')
LOG.mkdir(exist_ok=True)
BASE = LOG / 'test_rotation.jsonl'
# Remove existing artifacts
for p in LOG.glob('test_rotation.jsonl*'):
    try:
        p.unlink()
    except Exception:
        pass

# Configure writer small max_bytes to force many rotations
writer = _JsonlWriter(BASE, max_bytes=1024, retention_days=1, compress=True, retention_files=5)

# Generate many entries
N = 200
for i in range(N):
    rec = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime()) + 'Z',
        'run_id': 'test',
        'event_code': 'ORDER.SUBMIT',
        'cid': f'cid-{i}-{random.randint(0,1000)}',
        'oid': None,
        'side': random.choice(['buy','sell']),
        'price': round(random.random()*100, 2),
        'qty': round(random.random()*5, 3),
    }
    writer.write_line(json.dumps(rec, ensure_ascii=False))

# Allow flush/purge
time.sleep(0.2)

gz = sorted([p for p in LOG.glob('test_rotation.jsonl.*.jsonl.gz')])
active = LOG / 'test_rotation.jsonl'
plain = [p for p in LOG.glob('test_rotation.jsonl.*.jsonl') if not p.name.endswith('.gz')]

ok = True
out = []
# Check count
if len(gz) > 5:
    ok = False
    out.append(f"TOO_MANY_GZ={len(gz)}")
else:
    out.append(f"GZ_COUNT={len(gz)}")
# Ensure active exists
if not active.exists():
    ok = False
    out.append("ACTIVE_MISSING")
else:
    out.append("ACTIVE_PRESENT")

# Validate last line in each gz is valid JSON
import gzip
for p in gz:
    try:
        with gzip.open(p, 'rt', encoding='utf-8') as fh:
            lines = fh.read().splitlines()
            if not lines:
                ok = False
                out.append(f"EMPTY_ARCHIVE:{p.name}")
            else:
                try:
                    last = json.loads(lines[-1])
                except Exception as e:
                    ok = False
                    out.append(f"BAD_JSON:{p.name}:{e}")
                # optional: check ts has Z suffix if 'ts' present
                if isinstance(last.get('ts'), str) and not last.get('ts').endswith('Z'):
                    ok = False
                    out.append(f"TS_NOT_ISOZ:{p.name}")
    except Exception as e:
        ok = False
        out.append(f"GZ_OPEN_ERR:{p.name}:{e}")

# Write result
res = LOG / 'rotation_ok.txt'
with res.open('w', encoding='utf-8') as fh:
    if ok:
        fh.write('OK\n')
    else:
        fh.write('FAIL\n')
        for l in out:
            fh.write(l + '\n')
print('Done:', res, 'OK' if ok else 'FAIL')
