from __future__ import annotations

import sys
import subprocess
from pathlib import Path


def test_summary_gate_exits_nonzero_on_fail(tmp_path: Path):
    # Prepare minimal summary and events that will trigger a FAIL due to high slippage ratio
    summary_path = tmp_path / "canary_60min_summary.md"
    events_path = tmp_path / "events.jsonl"

    # Create a fake summary with slip_mae_ratio above default threshold (0.30)
    summary_md = """
    # Canary Summary

    MAE (bps): 12.3
    slip_mae_ratio: 0.50

    | code | count | percent |
    | expected_return_gate | 0 | 0% |
    """.strip()
    summary_path.write_text(summary_md, encoding="utf-8")

    # Empty events file (no latency or risk events required for this test)
    events_path.write_text("\n", encoding="utf-8")

    repo_root = Path(__file__).resolve().parents[2]
    gate_script = repo_root / "tools" / "summary_gate.py"

    # Run the gate script pointing to our temp files
    proc = subprocess.run(
        [sys.executable, "-u", str(gate_script), "--summary", str(summary_path), "--events", str(events_path), "--strict"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )

    # It should print FAIL and exit with non-zero code
    assert proc.returncode != 0, f"Expected non-zero exit, got {proc.returncode}. stdout={proc.stdout} stderr={proc.stderr}"
    assert "SUMMARY GATE: FAIL" in proc.stdout, f"Expected FAIL marker in stdout. stdout={proc.stdout}"
