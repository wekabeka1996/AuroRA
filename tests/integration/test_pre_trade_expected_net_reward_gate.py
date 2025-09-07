import json
import tempfile
from pathlib import Path

from tools import replay


def test_expected_net_reward_gate_blocks_when_negative():
    # Create a minimal profile with a high threshold so that expected_pnl_proxy < threshold
    base_profile = {
        "sizing": {
            "limits": {"max_notional_usd": 50},
            "kelly_scaler": 0.05
        },
        "reward": {
            "expected_net_reward_threshold_bps": 10000.0,  # very high -> force block
        },
        "universe": {"ranking": {"top_n": 3}}
    }

    # Create temporary replay data directory with one minimal jsonl file
    with tempfile.TemporaryDirectory() as td:
        replay_dir = Path(td) / "replay_30d"
        replay_dir.mkdir(parents=True, exist_ok=True)
        # write a single dummy event line to satisfy create_replay_engine
        with open(replay_dir / "sample.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"ts_ns": "0", "details": {}}) + "\n")

        # Write profile to a temp file
        prof_path = Path(td) / "profile.yaml"
        prof_path.write_text(json.dumps(base_profile))

        # Run replay (will write logs/aurora_events.jsonl in cwd)
        out_json = Path(td) / "metrics.json"
        # Ensure logs dir is isolated to temp dir by chdir
        cwd = Path.cwd()
        try:
            Path(td).mkdir(exist_ok=True)
            # run_replay writes to logs/aurora_events.jsonl in project root; chdir to temp
            import os
            os.chdir(td)
            metrics = replay.run_replay(str(replay_dir), str(prof_path), str(out_json), strict=False)
        finally:
            os.chdir(cwd)

        # Read generated logs
        logs_file = Path(td) / "logs" / "aurora_events.jsonl"
        assert logs_file.exists(), "Expected aurora_events.jsonl to be created"

        found = False
        with open(logs_file, "r", encoding="utf-8") as lf:
            for line in lf:
                ev = json.loads(line)
                if ev.get("event_code") == "EXPECTED_NET_REWARD_GATE":
                    found = True
                    details = ev.get("details", {})
                    assert details.get("outcome") == "blocked"
                    assert "threshold" in details
                    assert "expected_pnl_proxy" in details
                    assert "expected_cost_total" in details
        assert found, "EXPECTED_NET_REWARD_GATE event not found in logs"
