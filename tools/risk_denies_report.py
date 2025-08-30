from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Extract RISK.DENY events to CSV")
    from os import getenv
    default_events = str(Path(getenv('AURORA_SESSION_DIR', 'logs')) / 'aurora_events.jsonl')
    p.add_argument("--in", dest="inp", default=default_events, help="Path to aurora_events.jsonl (or legacy events.jsonl)")
    p.add_argument("--out", dest="out", required=True, help="Output CSV path")
    return p.parse_args()


def extract_fields(evt: dict[str, Any]) -> dict[str, Any]:
    ts = evt.get("ts") or evt.get("timestamp") or "N/A"
    code = evt.get("event_code") or evt.get("code") or evt.get("type") or "N/A"
    pl = evt.get("payload") or evt.get("details") or {}
    ctx = pl.get("ctx") or {}
    return {
        "ts": ts,
        "code": code,
        "dd_cap_pct": ctx.get("dd_cap_pct", "N/A"),
        "dd_used_pct": ctx.get("dd_used_pct", "N/A"),
        "pnl_today": ctx.get("pnl_today_pct", "N/A"),
        "max_concurrent": ctx.get("max_concurrent", "N/A"),
        "open_positions": ctx.get("open_positions", "N/A"),
        "size_scale": ctx.get("size_scale", "N/A"),
        "base_notional": ctx.get("base_notional", "N/A"),
        "scaled_notional": ctx.get("scaled_notional", "N/A"),
    }


def main():
    args = parse_args()
    in_path = Path(args.inp)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    with in_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except Exception:
                continue
            if (evt.get("event_code") or evt.get("type") or evt.get("code")) not in ("RISK.DENY",):
                continue
            rows.append(extract_fields(evt))

    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(
            f,
            fieldnames=[
                "ts",
                "code",
                "dd_cap_pct",
                "dd_used_pct",
                "pnl_today",
                "max_concurrent",
                "open_positions",
                "size_scale",
                "base_notional",
                "scaled_notional",
            ],
        )
        w.writeheader()
        w.writerows(rows)

    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    main()
