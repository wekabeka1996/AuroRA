#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parent.parent


def run(args_list: list[str]) -> int:
    return subprocess.run(args_list, cwd=str(ROOT)).returncode


def ensure_env(mode: str) -> None:
    m = str(mode).lower().strip()
    if m == "testnet":
        os.environ.setdefault("EXCHANGE_TESTNET", "true")
        # Removed legacy 'shadow' mode; require explicit testnet selection
        if os.environ.get('AURORA_MODE', '').lower().strip() == 'shadow':
            raise RuntimeError("Removed legacy 'shadow' mode; use --mode testnet or set AURORA_MODE=testnet")
        os.environ.setdefault("AURORA_MODE", "testnet")
        os.environ.setdefault("DRY_RUN", "false")
    elif m == "live":
        os.environ["EXCHANGE_TESTNET"] = "false"
        os.environ.setdefault("AURORA_MODE", "prod")
        os.environ.setdefault("DRY_RUN", "false")
    else:
        raise SystemExit(2)


def wait_health(timeout_sec: int, endpoint: str = "health") -> bool:
    deadline = time.time() + max(0, int(timeout_sec))
    while time.time() < deadline:
        rc = run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "health", "--endpoint", endpoint])
        if rc == 0:
            return True
        time.sleep(1.0)
    return False


def main():
    ap = argparse.ArgumentParser(description="Start Aurora API and trading run in one script")
    ap.add_argument("--mode", choices=["testnet", "live"], default="testnet")
    ap.add_argument("--minutes", type=int, default=15, help="Duration of trading run")
    ap.add_argument("--metrics-window", type=str, default=None, help="Metrics window in seconds or expression (e.g., 900 or 720*60)")
    ap.add_argument("--preflight", action="store_true", help="Run smoke checks before trading on testnet")
    ap.add_argument("--analytics", action="store_true", help="Start monitoring stack via docker compose if available")
    ap.add_argument("--keep-api", action="store_true", help="Do not stop API at the end")
    ap.add_argument("--ignore-health", action="store_true", help="Proceed even if /health is not OK")
    ap.add_argument("--health-timeout-sec", type=int, default=30)
    args = ap.parse_args()

    ensure_env(args.mode)

    # 1) Wallet check
    rc = run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "wallet-check"])
    if rc != 0:
        print(f"wallet-check failed rc={rc}")
        raise SystemExit(rc)

    # 2) Monitoring
    if args.analytics and (ROOT / "docker-compose.yml").exists():
        try:
            subprocess.run(["docker", "compose", "up", "-d", "--build"], cwd=str(ROOT), check=False)
        except Exception:
            print("analytics skipped (docker not available)")

    # 3) Start API (best-effort; health will confirm)
    run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "start-api"])

    # 4) Wait health
    # For testnet, liveness is enough; for live, require readiness
    ep = "readiness" if args.mode == "live" else "liveness"
    ok = wait_health(args.health_timeout_sec, endpoint=ep)
    print(f"health: {'OK' if ok else 'NOT_READY'}")
    if not ok and not args.ignore_health and args.mode == "live":
        # In live mode, enforce health unless --ignore-health
        print("/health is not OK; aborting (use --ignore-health to proceed)")
        run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "stop-api"])  # stop before exit
        raise SystemExit(1)

    # 5) Run trading
    try:
        if args.mode == "testnet":
            cmd = [sys.executable, str(ROOT / "tools" / "run_live_testnet.py"), "--minutes", str(args.minutes), "--load-dotenv"]
            if args.preflight:
                cmd.append("--preflight")
            rc_run = run(cmd)
        else:
            rc_run = run([sys.executable, str(ROOT / "tools" / "run_canary.py"), "--minutes", str(args.minutes)])
    except KeyboardInterrupt:
        rc_run = 130

    # 6) Metrics
    rc_metrics = 0
    if args.metrics_window:
        rc_metrics = run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "metrics", "--window-sec", str(args.metrics_window)])

    # 7) Stop API
    if not args.keep_api:
        run([sys.executable, str(ROOT / "tools" / "auroractl.py"), "stop-api"])

    final_rc = rc_run if rc_run != 0 else rc_metrics
    print(f"done: canary_rc={rc_run} metrics_rc={rc_metrics}")
    raise SystemExit(final_rc)


if __name__ == "__main__":
    main()
