from __future__ import annotations

import os
import json
from core.execution.sim_local_sink import SimLocalSink


def main():
    # Use a deterministic seed so the generated file includes rng_seed in the first event
    cfg = {'order_sink': {'sim_local': {'seed': 12345}}}
    sink = SimLocalSink(cfg)
    os.makedirs('logs', exist_ok=True)
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
