from __future__ import annotations

import os

from tools.gen_sim_local_first100 import main as gen_main


def test_gen_sim_local_first100_creates_events():
    # ensure logs dir and run generator
    if os.path.exists('logs/aurora_events.jsonl'):
        os.remove('logs/aurora_events.jsonl')
    gen_main()
    assert os.path.exists('logs/aurora_events.jsonl')
    # file has at least one line
    with open('logs/aurora_events.jsonl', 'r', encoding='utf8') as f:
        lines = [l.strip() for l in f if l.strip()]
    assert len(lines) >= 1
