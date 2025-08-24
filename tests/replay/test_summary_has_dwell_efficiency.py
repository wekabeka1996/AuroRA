import json
from pathlib import Path


def test_summary_contains_dwell_efficiency(tmp_path: Path):
    summary = {
        "alpha_target": 0.1,
        "coverage_empirical": 0.92,
        "dwell_efficiency": 0.6,
    }
    p = tmp_path / "summary.json"
    p.write_text(json.dumps(summary), encoding="utf-8")
    loaded = json.loads(p.read_text(encoding="utf-8"))
    assert "dwell_efficiency" in loaded
    val = float(loaded["dwell_efficiency"])
    assert 0.0 <= val <= 1.0
