from __future__ import annotations

import sys
import subprocess
import json
from pathlib import Path


def run_gate(summary: Path, events: Path, status_out: Path, extra_args: list[str] | None = None):
    repo_root = Path(__file__).resolve().parents[2]
    gate_script = repo_root / "tools" / "summary_gate.py"
    args = [sys.executable, "-u", str(gate_script), "--summary", str(summary), "--events", str(events), "--strict", "--status-out", str(status_out)]
    if extra_args:
        args.extend(extra_args)
    return subprocess.run(args, cwd=str(repo_root), capture_output=True, text=True)


def test_gate_ok(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    summary = repo / "tests" / "fixtures" / "ok_summary.md"
    events = repo / "tests" / "fixtures" / "ok_events.jsonl"
    status = tmp_path / "ok_status.json"
    proc = run_gate(summary, events, status)
    assert proc.returncode == 0, f"Expected exit 0, got {proc.returncode}. stdout={proc.stdout} stderr={proc.stderr}"
    assert "SUMMARY GATE: OK" in proc.stdout
    assert status.exists(), "Status JSON must be written"
    data = json.loads(status.read_text(encoding="utf-8"))
    assert data.get("result") == "OK"


def test_gate_fail(tmp_path: Path):
    repo = Path(__file__).resolve().parents[2]
    summary = repo / "tests" / "fixtures" / "fail_summary.md"
    events = repo / "tests" / "fixtures" / "fail_events.jsonl"
    status = tmp_path / "fail_status.json"
    proc = run_gate(summary, events, status)
    assert proc.returncode != 0, f"Expected non-zero exit, got {proc.returncode}. stdout={proc.stdout} stderr={proc.stderr}"
    assert "SUMMARY GATE: FAIL" in proc.stdout
    assert status.exists(), "Status JSON must be written"
    data = json.loads(status.read_text(encoding="utf-8"))
    assert data.get("result") == "FAIL"
    # Should contain at least one violation reason string
    assert isinstance(data.get("violations"), list) and len(data["violations"]) >= 1
