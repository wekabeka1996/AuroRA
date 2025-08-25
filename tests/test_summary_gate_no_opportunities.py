import json
import subprocess
from pathlib import Path


def write_file(p: Path, content: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def test_summary_gate_no_opportunities_strict(tmp_path: Path):
    # Minimal MD without latency/slip and without reasons indicating accept
    md = """
# Canary 60min Summary

## Reasons table

| code | count | percent |
|---|---:|---:|
| expected_return_gate | 0 | 0.0% |

## Risk

| risk_reason | count |
|---|---:|
| N/A | 0 |
""".strip()
    events = [
        # Some non-accept events
        {"type": "POLICY.DECISION", "payload": {"reasons": ["slippage_guard"]}},
        {"type": "RISK.DENY", "payload": {"reason": "MAX_CONCURRENT"}},
        {"type": "HEALTH.LATENCY_WARN", "payload": {"latency_ms": 22}},
    ]

    md_path = tmp_path / "reports" / "canary_60min_summary.md"
    ev_path = tmp_path / "logs" / "events.jsonl"
    write_file(md_path, md)
    write_file(ev_path, "\n".join(json.dumps(e) for e in events))

    status_out = tmp_path / "reports" / "status.json"
    cmd = [
        "python",
        str(Path("tools") / "summary_gate.py"),
        "--summary",
        str(md_path),
        "--events",
        str(ev_path),
        "--strict",
        "--status-out",
        str(status_out),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode == 1, f"Gate should fail, got rc={proc.returncode}, out={proc.stdout}, err={proc.stderr}"
    # Check violation NO_VALID_OPPORTUNITIES present
    full_out = proc.stdout + "\n" + proc.stderr
    assert "NO_VALID_OPPORTUNITIES" in full_out
    # Status JSON written with computed.expected_return_accepts == 0
    data = json.loads(status_out.read_text(encoding="utf-8"))
    assert data["result"] == "FAIL"
    assert any(v == "NO_VALID_OPPORTUNITIES" for v in data.get("violations", []))
    assert int(data.get("computed", {}).get("expected_return_accepts", -1)) == 0
