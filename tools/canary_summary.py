from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter
from statistics import quantiles
from pathlib import Path

# Ensure project root on sys.path for local package imports
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from observability.codes import (
    POLICY_DECISION,
    RISK_DENY,
    normalize_reason,
)


def parse_events(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def export_timeseries(events: list[dict], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    # Expect latency in observability if present
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["idx", "type", "latency_ms", "reason"])
        for i, ev in enumerate(events):
            t = ev.get("type")
            payload = ev.get("payload", {})
            obs = payload.get("observability", {}) if isinstance(payload, dict) else {}
            latency = obs.get("latency_ms") or payload.get("latency_ms")
            reason = None
            if t == "POLICY.DECISION":
                reason = payload.get("reasons")
            w.writerow([i, t, latency, reason])


def export_escalations(events: list[dict], out_md: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# Escalations flow\n"]
    for ev in events:
        t = ev.get("type")
        if str(t).startswith("AURORA.") or str(t).startswith("HEALTH."):
            lines.append(f"- {t}: {json.dumps(ev.get('payload', {}))}")
    out_md.write_text("\n".join(lines), encoding="utf-8")


def summarize_reasons(events: list[dict]) -> tuple[Counter, Counter]:
    codes = Counter()
    risk_codes = Counter()
    for ev in events:
        t = str(ev.get("type") or "").upper()
        code = str(ev.get("code") or "")
        payload = ev.get("payload") or {}
        # Count decision reasons from POLICY.DECISION
        if t == POLICY_DECISION:
            reasons = payload.get("reasons") or []
            if isinstance(reasons, list):
                for r in reasons:
                    key = normalize_reason(str(r))
                    codes[key] += 1
        # Count explicit codes from other events
        if code:
            codes[code] += 1
        if t == RISK_DENY:
            r = (payload.get("reason") or ev.get("code") or "RISK.DENY").strip()
            risk_codes[r] += 1
    return codes, risk_codes


def slippage_stats(events: list[dict]) -> tuple[str, str]:
    model_vals = []
    realized_vals = []
    for ev in events:
        payload = ev.get("payload") or {}
        sl = payload.get("slippage") or {}
        mb_raw = sl.get("model_bps")
        rb_raw = sl.get("realized_bps")
        try:
            if mb_raw is None or rb_raw is None:
                continue
            mb = float(mb_raw)
            rb = float(rb_raw)
            model_vals.append(mb)
            realized_vals.append(rb)
        except Exception:
            continue
    if not model_vals or not realized_vals:
        return "N/A", "N/A"
    import math
    n = min(len(model_vals), len(realized_vals))
    abs_err = [abs(realized_vals[i] - model_vals[i]) for i in range(n)]
    mae = sum(abs_err) / n if n > 0 else float("nan")
    mean_model = sum(model_vals[:n]) / n if n > 0 else 0.0
    if mean_model == 0:
        ratio = "N/A"
    else:
        ratio = f"{mae/mean_model:.4f}"
    return f"{mae:.4f}", ratio


def fallback_latency_p95(events: list[dict]) -> float | None:
    # Try extract latency_ms from observability or payload; compute p95 over all
    vals: list[float] = []
    for ev in events:
        try:
            payload = ev.get("payload") or {}
            obs = payload.get("observability", {}) if isinstance(payload, dict) else {}
            v = obs.get("latency_ms") or payload.get("latency_ms")
            if v is None:
                continue
            vals.append(float(v))
        except Exception:
            continue
    if not vals:
        return None
    try:
        # statistics.quantiles default n=4; specify to approx p95
        qs = quantiles(sorted(vals), n=100)
        return float(qs[94])
    except Exception:
        try:
            import numpy as np  # type: ignore
            return float(np.percentile(vals, 95))
        except Exception:
            return None


def fallback_slip_ratio(events: list[dict]) -> float | None:
    # Approximate slip ratio if model/realized not present
    num = []
    den = []
    for ev in events:
        try:
            payload = ev.get("payload") or {}
            sl = payload.get("slippage") or {}
            eff = sl.get("effective_spread")
            q = sl.get("quoted_spread")
            if eff is None or q is None:
                # fallback to bps
                mb = sl.get("model_bps") or payload.get("slip_bps")
                qb = payload.get("b_bps") or payload.get("quoted_bps")
                if mb is None or qb is None:
                    continue
                num.append(abs(float(mb)))
                den.append(abs(float(qb)))
            else:
                num.append(abs(float(eff)))
                den.append(abs(float(q)))
        except Exception:
            continue
    if not num or not den:
        return None
    try:
        # mean of point ratios; guard zero
        ratios = [ (n / d) for n, d in zip(num, den) if d not in (0.0, 0) ]
        return float(sum(ratios) / max(1, len(ratios))) if ratios else None
    except Exception:
        return None


def write_summary_md(events: list[dict], out_md: Path) -> None:
    out_md.parent.mkdir(parents=True, exist_ok=True)
    codes, risk_codes = summarize_reasons(events)
    total = sum(codes.values()) or 1
    mae, ratio = slippage_stats(events)
    # Fallbacks if N/A
    if ratio == "N/A":
        r_f = fallback_slip_ratio(events)
        if r_f is not None:
            ratio = f"{r_f:.4f}"
    lat_p95_f = fallback_latency_p95(events)
    lines = ["# Canary 60min Summary", ""]
    # Reasons table
    lines += ["## Reasons table", "", "| code | count | percent |", "|---|---:|---:|"]
    for code, cnt in codes.most_common():
        pct = 100.0 * cnt / total
        lines.append(f"| {code} | {cnt} | {pct:.1f}% |")
    # Risk section
    lines += ["", "## Risk", "", "| risk_reason | count |", "|---|---:|"]
    if risk_codes:
        for code, cnt in risk_codes.most_common():
            lines.append(f"| {code} | {cnt} |")
    else:
        lines.append("| N/A | 0 |")
    # Slippage section
    lines += ["", "## Slippage", "", f"MAE (bps): {mae}", f"slip_mae_ratio: {ratio}"]
    if lat_p95_f is not None:
        lines += ["", "## Latency", "", f"latency_p95_ms: {lat_p95_f:.2f}"]
    out_md.write_text("\n".join(lines), encoding="utf-8")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--events", default="logs/events.jsonl")
    p.add_argument("--out-ts", default="reports/latency_p95_timeseries.csv")
    p.add_argument("--out-flow", default="reports/escalations_flow.md")
    p.add_argument("--out-md", default="reports/canary_60min_summary.md")
    args = p.parse_args()

    events = parse_events(Path(args.events))
    export_timeseries(events, Path(args.out_ts))
    export_escalations(events, Path(args.out_flow))
    write_summary_md(events, Path(args.out_md))
    print(f"Wrote {args.out_ts}, {args.out_flow} and {args.out_md}")


if __name__ == "__main__":
    main()
