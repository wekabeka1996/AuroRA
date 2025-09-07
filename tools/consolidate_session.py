#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent


def _find_latest_session_dir(logs_root: Path) -> Optional[Path]:
    if not logs_root.exists():
        return None
    # Prefer subdirs named as timestamps (YYYYMMDD-HHMMSS)
    cand = []
    for p in logs_root.iterdir():
        if p.is_dir() and re.match(r"^\d{8}-\d{6}$", p.name):
            cand.append(p)
    if not cand:
        return logs_root if any(logs_root.glob("*.jsonl")) else None
    cand.sort(key=lambda p: p.name)
    return cand[-1]


def _copy_if_exists(src: Path, dst: Path) -> bool:
    try:
        if src.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            return True
    except Exception:
        pass
    return False


def _copy_glob(src_glob: str, dst_dir: Path) -> int:
    import glob
    n = 0
    for fp in glob.glob(src_glob):
        sp = Path(fp)
        if sp.exists() and sp.is_file():
            try:
                dst = dst_dir / sp.name
                dst_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(sp, dst)
                n += 1
            except Exception:
                pass
    return n


def _count_events(jsonl: Path, substr: str) -> int:
    c = 0
    try:
        with jsonl.open("r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                if substr in ln:
                    c += 1
    except Exception:
        pass
    return c


def _fetch_metrics_snapshot(base_url: str = "http://127.0.0.1:8000") -> Tuple[Optional[str], Optional[str]]:
    try:
        import requests
    except Exception:
        return None, None
    # Try /metrics and /ops/model_status (ops token optional)
    metrics_txt = None
    model_status = None
    try:
        r = requests.get(f"{base_url}/metrics", timeout=1.5)
        if r.ok:
            metrics_txt = r.text
    except Exception:
        pass
    token = os.getenv("AURORA_OPS_TOKEN") or os.getenv("OPS_TOKEN")
    headers = {"X-OPS-TOKEN": token} if token else {}
    try:
        r2 = requests.get(f"{base_url}/ops/model_status", headers=headers, timeout=1.5)
        if r2.ok:
            model_status = r2.text
    except Exception:
        pass
    return metrics_txt, model_status


def main():
    ap = argparse.ArgumentParser(description="Consolidate Aurora session artifacts into runs/<ts>")
    ap.add_argument("--session-root", default=None, help="Explicit session dir to consolidate (defaults to latest under logs/)")
    ap.add_argument("--orchestrator-events", default=None, help="Path to orchestrator events jsonl (defaults to artifacts/online_optuna_events.jsonl)")
    ap.add_argument("--base-url", default="http://127.0.0.1:8000", help="API base URL for metrics/model snapshot")
    args = ap.parse_args()

    logs_root = ROOT / "logs"
    session_dir: Optional[Path]
    if args.session_root:
        session_dir = Path(args.session_root)
    else:
        session_dir = _find_latest_session_dir(logs_root)

    ts = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    run_root = ROOT / "runs" / ts
    run_root.mkdir(parents=True, exist_ok=True)

    # 1) Copy session logs
    src_session = session_dir if session_dir and session_dir.exists() else None
    copied = {"aurora_events": False, "orders": 0}
    if src_session is not None:
        copied["aurora_events"] = _copy_if_exists(src_session / "aurora_events.jsonl", run_root / "aurora_events.jsonl")
        for name in ["orders_success.jsonl", "orders_failed.jsonl", "orders_denied.jsonl", "orders.jsonl"]:
            if _copy_if_exists(src_session / name, run_root / name):
                copied["orders"] += 1

    # 2) Copy flat logs/*.jsonl as additional context
    copied_flat = _copy_glob(str(logs_root / "*.jsonl"), run_root)

    # 3) Copy orchestrator events
    orch_path = Path(args.orchestrator_events) if args.orchestrator_events else (ROOT / "artifacts" / "online_optuna_events.jsonl")
    orch_copied = _copy_if_exists(orch_path, run_root / "online_optuna_events.jsonl")

    # 4) Fetch metrics snapshots from API (best-effort)
    metrics_txt, model_status = _fetch_metrics_snapshot(args.base_url)
    if metrics_txt:
        try:
            (run_root / "metrics.txt").write_text(metrics_txt, encoding="utf-8")
        except Exception:
            pass
    if model_status:
        try:
            (run_root / "model_status.json").write_text(model_status, encoding="utf-8")
        except Exception:
            pass

    # 5) Produce a tiny summary.json
    enr_count = 0
    parent_count = 0
    ev_path = run_root / "aurora_events.jsonl"
    if ev_path.exists():
        enr_count = _count_events(ev_path, "EXPECTED_NET_REWARD_GATE")
        parent_count = _count_events(ev_path, "PARENT_GATE.EVAL")

    summary = {
        "run_root": str(run_root),
        "source_session": str(src_session) if src_session else None,
        "aurora_events_copied": bool(copied.get("aurora_events")),
        "orders_files_copied": copied.get("orders", 0),
        "flat_logs_copied": copied_flat,
        "orchestrator_events_copied": bool(orch_copied),
        "expected_net_reward_events": enr_count,
        "parent_gate_eval_events": parent_count,
        "metrics_captured": bool(metrics_txt),
        "model_status_captured": bool(model_status),
    }
    try:
        (run_root / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass

    # Print a short human message for CLI users
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
