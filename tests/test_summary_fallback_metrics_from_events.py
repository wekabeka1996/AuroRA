import json
import subprocess
from pathlib import Path


def write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def test_canary_summary_fallback_metrics(tmp_path: Path):
    # Prepare minimal events with observability.latency_ms and slippage bps nested
    events = []
    # Create 100 events with increasing latency
    for i in range(1, 101):
        events.append({
            "type": "POLICY.DECISION",
            "payload": {
                "reasons": ["expected_return_accept" if i % 10 == 0 else "slippage_guard"],
                "observability": {"latency_ms": 10 + i * 0.5, "slip_bps_est": 2.0, "b_bps": 20.0},
            },
        })

    ev_path = tmp_path / "logs" / "events.jsonl"
    write_jsonl(ev_path, events)

    out_md = tmp_path / "reports" / "canary_60min_summary.md"
    out_ts = tmp_path / "reports" / "latency_p95_timeseries.csv"
    out_flow = tmp_path / "reports" / "escalations_flow.md"

    cmd = [
        "python",
        str(Path("tools") / "canary_summary.py"),
        "--events",
        str(ev_path),
        "--out-md",
        str(out_md),
        "--out-ts",
        str(out_ts),
        "--out-flow",
        str(out_flow),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    # Now run summary_gate to materialize status JSON and check computed fields
    status_out = tmp_path / "reports" / "status.json"
    cmd2 = [
        "python",
        str(Path("tools") / "summary_gate.py"),
        "--summary",
        str(out_md),
        "--events",
        str(ev_path),
        "--status-out",
        str(status_out),
    ]
    proc2 = subprocess.run(cmd2, capture_output=True, text=True)
    assert proc2.returncode in (0,1)
    data = json.loads(status_out.read_text(encoding="utf-8"))
    lat = data.get("computed", {}).get("latency_p95_ms")
    slip = data.get("computed", {}).get("slip_ratio")
    assert lat is not None and lat != "N/A"
    assert slip is not None and slip != "N/A"
