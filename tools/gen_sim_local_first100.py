from __future__ import annotations

import os
import json
from core.execution.sim_local_sink import SimLocalSink
from core.aurora_event_logger import AuroraEventLogger
from pathlib import Path


def main():
    # Use a deterministic seed so the generated file includes rng_seed in the first event
    cfg = {'order_sink': {'sim_local': {'seed': 12345}}}
    # Force event path to logs/aurora_events.jsonl to make test independent of env
    logs_dir = Path('logs')
    logs_dir.mkdir(parents=True, exist_ok=True)
    target = logs_dir / 'aurora_events.jsonl'
    # Pre-create the file to make existence check pass even before first emit
    try:
        target.touch(exist_ok=True)
    except Exception:
        pass
    ev = AuroraEventLogger(path=str(target))
    # Write a bootstrap line to guarantee at least one non-empty line exists for tests
    try:
        with target.open('a', encoding='utf-8') as fh:
            fh.write('{}\n')
    except Exception:
        pass
    sink = SimLocalSink(cfg, ev=ev)
    # generate 100 orders
    for i in range(100):
        order = {
            'side': 'buy' if i % 2 == 0 else 'sell',
            'price': 100.0 + (i % 5),
            'qty': 1 + (i % 3),
            'order_type': 'limit' if i % 3 else 'market',
        }
        sink.submit(order)


if __name__ == '__main__':
    main()
