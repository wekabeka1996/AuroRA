#!/usr/bin/env python3
"""Direct test using _JsonlWriter to bypass dedupe and force rotations.
"""
from pathlib import Path
import time, json
import sys
from pathlib import Path
repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))
from core.order_logger import _JsonlWriter

LOG_DIR = Path('logs')
LOG_DIR.mkdir(exist_ok=True)
base = LOG_DIR / 'direct_events.jsonl'
# cleanup
for p in LOG_DIR.glob('direct_events.jsonl*'):
    try:
        p.unlink()
    except Exception:
        pass

w = _JsonlWriter(base, max_bytes=1024, retention_days=1)
# write many small lines to force rotations
for i in range(1000):
    line = json.dumps({'i': i, 'ts_iso': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())})
    w.write_line(line)
# collect parts
parts = sorted([p for p in LOG_DIR.glob('direct_events.jsonl.*.part*.jsonl')])
print('parts_count=', len(parts))
for p in parts[:10]:
    print('part:', p.name)
# check current
if base.exists():
    print('current:', base.name)

# check gz archives
gz = sorted([p for p in LOG_DIR.glob('direct_events.jsonl.*.jsonl.gz')])
print('gz_count=', len(gz))
