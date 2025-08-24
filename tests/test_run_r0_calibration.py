import json, os, sys, csv, tempfile, shutil, subprocess
from pathlib import Path

def _write_minilog(dirpath: Path):
    d = dirpath / "shadow_logs"
    d.mkdir(parents=True, exist_ok=True)
    rows = []
    for i in range(12):
        mu = 100.0 + (i % 3 - 1) * 0.5
        sigma = 5.0
        lo, hi = mu - 0.5, mu + 0.5
        latency = 80 if i % 4 else 160
        rows.append({
            "ts": f"2025-08-17T12:{i:02d}:00Z",
            "symbol": "TESTUSDT",
            "mu": mu,
            "sigma": sigma,
            "interval": {"lo": lo, "hi": hi},
            "latency_ms": latency
        })
    with open(d / "mini.jsonl", "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    return d

def test_run_r0_calibration_produces_artifacts():
    tmp = Path(tempfile.mkdtemp())
    try:
        logs_dir = _write_minilog(tmp)
        out_dir = tmp / "calib"
        out_dir.mkdir(parents=True, exist_ok=True)
        grid = "kappa.tau_pass=0.72,0.75;kappa.tau_derisk=0.48,0.50"
        cmd = [
            sys.executable, "-m", "living_latent.scripts.run_r0",
            "--logs_dir", str(logs_dir),
            "--profile", "default",
            "--seed", "1337",
            "--calibrate",
            "--grid", grid,
            "--calib-out-dir", str(out_dir),
            "--top-k", "3",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        assert res.returncode == 0, res.stderr
        csv_path = out_dir / "calib_results.csv"
        json_path = out_dir / "calib_topk.json"
        assert csv_path.exists(), "calib_results.csv not found"
        assert json_path.exists(), "calib_topk.json not found"
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            row = next(reader)
            for key in [
                "score", "coverage_empirical", "surprisal_p95", "latency_p95_ms",
                "decisions_share.PASS", "decisions_share.DERISK", "decisions_share.BLOCK",
                "kappa.tau_pass", "kappa.tau_derisk"
            ]:
                assert key in row, f"missing column: {key}"
        top = json.loads(json_path.read_text(encoding="utf-8"))
        assert "items" in top and len(top["items"]) > 0
        scores = [it["score"] for it in top["items"]]
        assert all(scores[i] >= scores[i+1] for i in range(len(scores)-1)), "top-k not sorted desc by score"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
