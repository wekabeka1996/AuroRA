from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

import numpy as np

from core.scalper.trap import TrapWindow, trap_from_book_deltas, trap_score_from_features
from tests.helpers.trap_sequences import (
    make_neutral_sequence,
    make_fake_wall_sequence,
    make_cancel_then_replenish,
)


def eval_synthetic(threshold: float = 0.65) -> dict:
    # Perf p95
    tw = TrapWindow(window_s=2.0, levels=5, history=240)
    lats = []
    for _ in range(50):
        seq = make_neutral_sequence(n=20)
        csum = sum(ev.size for ev in seq if ev.action == "cancel")
        asum = sum(ev.size for ev in seq if ev.action == "add")
        cancels = [csum / 5.0] * 5
        adds = [asum / 5.0] * 5
        t0 = time.perf_counter()
        _ = tw.update(cancels, adds, trades_cnt=2)
        lats.append((time.perf_counter() - t0) * 1000.0)
    p95_ms = float(np.percentile(np.array(lats, dtype=float), 95))

    # Fake wall cases (positives)
    positives = []
    for _ in range(10):
        seq = make_fake_wall_sequence(n=60, burst_ms=200)
        cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
        s = trap_score_from_features(cancel_ratio, rep_ms)
        positives.append(s >= threshold)

    # Neutral cases (negatives)
    negatives = []
    for _ in range(10):
        seq = make_neutral_sequence(n=200)
        cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
        s = trap_score_from_features(cancel_ratio, rep_ms)
        negatives.append(s >= threshold)

    # Cancel->Replenish (positives)
    positives2 = []
    for _ in range(10):
        seq = make_cancel_then_replenish(delay_ms=10)
        cancel_ratio, rep_ms, *_ = trap_from_book_deltas(seq)
        s = trap_score_from_features(cancel_ratio, rep_ms)
        positives2.append(s >= threshold)

    pos_hits = sum(positives) + sum(positives2)
    pos_total = len(positives) + len(positives2)
    neg_hits = sum(negatives)
    neg_total = len(negatives)

    fn_rate = float(1.0 - (pos_hits / max(1, pos_total)))
    fp_rate = float(neg_hits / max(1, neg_total))

    return {"threshold": threshold, "p95_ms": p95_ms, "fn_rate": fn_rate, "fp_rate": fp_rate}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=str, default="reports/trap_stats.json")
    parser.add_argument("--threshold", type=float, default=float(os.getenv("AURORA_TRAP_THRESHOLD", "0.65")))
    args = parser.parse_args()

    stats = eval_synthetic(threshold=args.threshold)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(json.dumps(stats))


if __name__ == "__main__":
    main()
