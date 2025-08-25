import json
from pathlib import Path

from core.scalper.trap import BookDelta, trap_from_book_deltas, trap_score_from_features


def main():
    # Minimal synthetic example to produce an artifact deterministically
    evs = [
        BookDelta(ts=0.00, side="bid", price=100.0, size=5.0, action="cancel"),
        BookDelta(ts=0.01, side="bid", price=100.0, size=5.0, action="add"),
        BookDelta(ts=0.02, side="bid", price=100.0, size=5.0, action="cancel"),
        BookDelta(ts=0.03, side="bid", price=100.0, size=5.0, action="add"),
    ]
    cancel_ratio, rep_ms, cancel_sum, add_sum = trap_from_book_deltas(evs)
    score = trap_score_from_features(cancel_ratio, rep_ms)
    report = {
        "cancel_ratio": cancel_ratio,
        "replenish_latency_ms": rep_ms,
        "trap_score": score,
        "cancel_sum": cancel_sum,
        "add_sum": add_sum,
    }
    out = Path("reports")
    out.mkdir(parents=True, exist_ok=True)
    (out / "trap_stats.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report))


if __name__ == "__main__":
    main()
