from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def load_events(path: Path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def load_summary_ratio(summary_md: Path) -> float | None:
    if not summary_md.exists():
        return None
    for line in summary_md.read_text(encoding="utf-8").splitlines():
        if line.startswith("slip_mae_ratio:"):
            try:
                return float(line.split(":", 1)[1].strip())
            except Exception:
                return None
    return None


essential = {
    "expected_return_gate",
    "sprt_accept",
}


def last_latency_p95_ms(latency_csv: Path) -> float | None:
    if not latency_csv.exists():
        return None
    try:
        # Accept headers variants: ts,p95_ms OR ts,value OR idx,latency_ms
        last_row = None
        with latency_csv.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                last_row = row
        if not last_row:
            return None
        for k in ("p95_ms", "value", "latency_ms"):
            if k in last_row and last_row[k] not in (None, ""):
                try:
                    return float(last_row[k])  # type: ignore[arg-type]
                except Exception:
                    continue
    except Exception:
        return None
    return None


def main():
    p = argparse.ArgumentParser()
    from os import getenv
    default_events = str(Path(getenv('AURORA_SESSION_DIR', 'logs')) / 'aurora_events.jsonl')
    p.add_argument("--events", default=default_events)
    p.add_argument("--summary", default="artifacts/canary_60min_summary.md")
    p.add_argument("--latency-ts", default="reports/latency_p95_timeseries.csv")
    args = p.parse_args()

    events = load_events(Path(args.events))
    ratio = load_summary_ratio(Path(args.summary))
    p95 = last_latency_p95_ms(Path(args.latency_ts))

    # counts
    er = 0
    trap_warn = 0
    risk_denies = 0
    for ev in events[-2000:]:
        code_full = str(ev.get("event_code") or ev.get("code") or ev.get("type") or "")
        t = str(ev.get("type") or "")
        if code_full in essential or t in essential:
            er += 1
        if code_full.startswith("HEALTH.LATENCY_"):
            trap_warn += 1
        if code_full == "RISK.DENY":
            risk_denies += 1

    fields = [
        f"latency_p95_ms={p95:.1f}" if p95 is not None else "latency_p95_ms=N/A",
        f"slip_ratio={ratio:.2f}" if ratio is not None else "slip_ratio=N/A",
        f"expected_return_accepts={er}",
        f"latency_events={trap_warn}",
        f"risk_denies={risk_denies}",
    ]
    print("SMOKE:" + " ".join(fields))


if __name__ == "__main__":
    main()
