#!/usr/bin/env python
"""Acceptance Attestation Helper

Purpose:
  Consolidate governance evidence (WHY_GOV_* denies) and core event artifacts
  into a single attestation JSON (C7 scope). Optionally generate new acceptance
  sessions in deterministic dry‑run mode.

Key Features:
  * Deterministic session generation for two governance paths:
      - alpha_exhaust
      - sprt_reject
  * Artifact hashing (SHA256) + line counts + sizes.
  * Aggregate deny counts + aggregate hash over core files.
  * Safety guard: refuses to run generation if DRY_RUN=false.

Usage Examples:
  # 1. Just aggregate existing sessions into a final JSON
  python tools/acceptance_attest.py \
      --sessions logs/session_c7g logs/session_c7sr_final \
      --output logs/C7_attestation_final.json

  # 2. Generate fresh sessions (timestamped) then attest
  python tools/acceptance_attest.py --generate alpha_exhaust sprt_reject \
      --output logs/C7_attestation_new.json

  # 3. Include metrics files if present
  python tools/acceptance_attest.py --sessions logs/session_c7sr_metrics \
      --output logs/C7_attestation_metrics.json

Environment (for generated runs):
  AURORA_MODE=live (required by runner, but DRY_RUN enforced true)
  AURORA_ACCEPTANCE_MODE=1
  AURORA_ACCEPTANCE_SCORE_OVERRIDE (set per scenario)

Scenarios:
  alpha_exhaust -> forces rapid alpha spending using positive score
  sprt_reject   -> forces ACCEPT_H0 using zero score (mean < delta/2)

Exit Codes:
  0 success
  2 invalid arguments / safety violation
  3 generation failure
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parent.parent
RUNNER_MODULE = "skalp_bot.runner.run_live_aurora"
BASE_CONFIG = "profiles/sol_soon_base.yaml"  # existing profile used in manual steps

SCENARIO_SPECS = {
    "alpha_exhaust": {
        "env": {
            "AURORA_MODE": "live",
            "DRY_RUN": "true",
            "AURORA_ACCEPTANCE_MODE": "1",
            "AURORA_EXPECTED_NET_REWARD_THRESHOLD_BPS": "-999",
            # Spend alpha quickly with high positive score (legacy boost path not used when override unset)
            "AURORA_ACCEPTANCE_SCORE_OVERRIDE": "0.7",
            "GOV_ALPHA0": "0.02",
            "GOV_SPEND_STEP": "0.0025",
            "GOV_DELTA": "0.05",
            "AURORA_MAX_TICKS": "40",
        },
        "expect_tags": ["WHY_GOV_ALPHA_EXHAUST"],
    },
    "sprt_reject": {
        "env": {
            "AURORA_MODE": "live",
            "DRY_RUN": "true",
            "AURORA_ACCEPTANCE_MODE": "1",
            "AURORA_EXPECTED_NET_REWARD_THRESHOLD_BPS": "-999",
            # Force ACCEPT_H0 by keeping score below delta/2
            "AURORA_ACCEPTANCE_SCORE_OVERRIDE": "0.0",
            "GOV_ALPHA0": "0.02",
            "GOV_SPEND_STEP": "0.001",
            "GOV_DELTA": "0.05",
            "AURORA_MAX_TICKS": "30",
        },
        "expect_tags": ["WHY_GOV_SPRT_REJECT"],
    },
}

CORE_FILES = ("aurora_events.jsonl", "orders_denied.jsonl")
OPTIONAL_FILES = ("metrics_9022.prom", "metrics_9030.prom")  # kept generic


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    with path.open("rb") as f:
        return sha256_bytes(f.read())


def count_lines(path: Path) -> int:
    # Efficient universal newline counting
    with path.open("rb") as f:
        return sum(1 for _ in f)


def run_scenario(name: str, out_dir: Path) -> Path:
    spec = SCENARIO_SPECS[name]
    session_dir = out_dir / f"session_{name}"
    if session_dir.exists():
        raise SystemExit(f"Refusing to overwrite existing {session_dir}")
    env = os.environ.copy()
    env.update(spec["env"])
    # Safety guard: enforce DRY_RUN true.
    if env.get("DRY_RUN", "true").lower() == "false":  # explicit
        print("[FATAL] DRY_RUN must remain true for acceptance generation", file=sys.stderr)
        raise SystemExit(2)
    env["AURORA_SESSION_DIR"] = str(session_dir)
    # Assign an ephemeral metrics port to avoid collision.
    base_port = 9100 if name == "alpha_exhaust" else 9105
    env["METRICS_PORT"] = str(base_port)
    cmd = [sys.executable, "-m", RUNNER_MODULE, "--config", BASE_CONFIG]
    print(f"[INFO] Running scenario {name} -> {session_dir}")
    completed = subprocess.run(cmd, env=env, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (session_dir / "_runner_stdout.log").write_text(completed.stdout, encoding="utf-8")
    print(f"[INFO] Scenario {name} exit code: {completed.returncode}")
    return session_dir


def collect_session(path: Path) -> Dict:
    info: Dict[str, Dict] = {}
    if not path.is_dir():
        return info
    deny_counts: Dict[str, int] = {}
    for fname in CORE_FILES + OPTIONAL_FILES:
        f = path / fname
        if not f.exists():
            continue
        data = f.read_bytes()
        info[fname] = {
            "sha256": sha256_bytes(data),
            "size_bytes": len(data),
            "lines": data.count(b"\n"),
        }
        if fname == "orders_denied.jsonl":
            for line in data.splitlines():
                if b"WHY_GOV_" in line:
                    for tag in (b"WHY_GOV_ALPHA_EXHAUST", b"WHY_GOV_SPRT_REJECT", b"WHY_GOV_NO_TOKEN"):
                        if tag in line:
                            deny_counts[tag.decode()] = deny_counts.get(tag.decode(), 0) + 1
    if deny_counts:
        info["deny_counts"] = deny_counts
    return info


def aggregate_hash(sessions: Dict[str, Dict]) -> str:
    hashes: List[str] = []
    for sess in sessions.values():
        for fname in CORE_FILES:
            meta = sess.get(fname)
            if meta:
                hashes.append(meta["sha256"])
    return sha256_bytes("".join(sorted(hashes)).encode())


def build_attestation(sessions: Dict[str, Dict]) -> Dict:
    aggregate_counts: Dict[str, int] = {}
    for sess in sessions.values():
        for k, v in sess.get("deny_counts", {}).items():
            aggregate_counts[k] = aggregate_counts.get(k, 0) + v
    return {
        "version": "C7-final-attestation",
        "generated_utc": dt.datetime.utcnow().isoformat() + "Z",
        "governance_evidence": sessions,
        "aggregate": {
            "deny_counts": aggregate_counts,
            "core_files_aggregate_sha256": aggregate_hash(sessions),
        },
    }


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser(
        description="Aggregate or generate acceptance governance evidence.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            """
            Scenarios:
              alpha_exhaust  - Exhaust alpha tokens (WHY_GOV_ALPHA_EXHAUST)
              sprt_reject    - Force SPRT statistical rejection (WHY_GOV_SPRT_REJECT)
            """
        ),
    )
    parser.add_argument("--sessions", nargs="*", default=[], help="Existing session directories to include.")
    parser.add_argument(
        "--generate", nargs="*", choices=sorted(SCENARIO_SPECS.keys()), help="Scenarios to generate before aggregation.")
    parser.add_argument("--output", required=True, help="Output attestation JSON path.")
    parser.add_argument("--skip-empty", action="store_true", help="Skip sessions producing zero denies.")
    args = parser.parse_args(argv)

    generated_dirs: Dict[str, Path] = {}
    if args.generate:
        out_root = ROOT / "logs" / ("acceptance_gen_" + dt.datetime.utcnow().strftime("%Y%m%d_%H%M%S"))
        out_root.mkdir(parents=True, exist_ok=False)
        for scen in args.generate:
            try:
                session_dir = run_scenario(scen, out_root)
            except Exception as e:  # noqa
                print(f"[ERROR] Scenario {scen} failed: {e}", file=sys.stderr)
                return 3
            generated_dirs[scen] = session_dir

    sessions: Dict[str, Dict] = {}
    # Include manually provided sessions
    for p in args.sessions:
        label = Path(p).name
        meta = collect_session(Path(p))
        if args.skip_empty and not meta.get("deny_counts"):
            continue
        sessions[label] = meta
    # Include generated ones
    for scen, path in generated_dirs.items():
        meta = collect_session(path)
        if args.skip_empty and not meta.get("deny_counts"):
            continue
        sessions[f"generated_{scen}"] = meta

    attestation = build_attestation(sessions)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(attestation, indent=2), encoding="utf-8")
    print(f"[OK] Wrote attestation -> {out_path}")
    print(json.dumps(attestation["aggregate"], indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main(sys.argv[1:]))
