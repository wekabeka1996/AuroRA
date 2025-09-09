#!/usr/bin/env python3
"""
Aurora testnet runner
====================

Wrapper script for running testnet cycles with Aurora API and trading bot.
This script handles:
- Environment setup for testnet mode
- Running the trading bot with proper configuration
- Smoke tests and validation
- Logging and cleanup

Usage:
    python tools/run_live_testnet.py --minutes 15 --preflight --runner-config profiles/btc_eth_testnet.yaml
"""

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

# Add project root to path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.auroractl import _exit


def main():
    parser = argparse.ArgumentParser(description="Aurora testnet runner")
    parser.add_argument("--minutes", type=int, default=5, help="Duration in minutes")
    parser.add_argument("--preflight", action="store_true", help="Run preflight checks")
    parser.add_argument("--runner-config", help="Runner configuration file path")
    parser.add_argument("--load-dotenv", action="store_true", help="Load .env file")
    args = parser.parse_args()

    print(f"Starting Aurora testnet run for {args.minutes} minutes")
    
    # Set testnet environment
    os.environ["AURORA_MODE"] = "testnet"
    os.environ["EXCHANGE_TESTNET"] = "true"
    os.environ.setdefault("DRY_RUN", "false")
    
    # Run preflight checks if requested
    if args.preflight:
        print("Running preflight smoke tests...")
        try:
            subprocess.run([
                sys.executable, 
                str(ROOT / "tools" / "auroractl.py"), 
                "smoke", 
                "--public-only"
            ], check=True, cwd=str(ROOT))
            print("Preflight checks passed")
        except subprocess.CalledProcessError as e:
            print(f"Preflight checks failed: {e}")
            _exit(1, "Preflight failed")

    # Prepare runner command
    runner_cmd = [
        sys.executable, 
        "-m", 
        "skalp_bot.runner.run_live_aurora"
    ]
    
    if args.runner_config:
        runner_cmd.extend(["--config", args.runner_config])
    
    # Set base URL to match API port
    runner_cmd.extend(["--base-url", "http://127.0.0.1:8000"])
    
    print(f"Starting trading bot with command: {' '.join(runner_cmd)}")
    
    # Run the trading bot
    try:
        # Calculate timeout with some buffer
        timeout_seconds = args.minutes * 60 + 30
        
        # Start the process
        process = subprocess.Popen(
            runner_cmd,
            cwd=str(ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Monitor the process with timeout
        start_time = time.time()
        end_time = start_time + (args.minutes * 60)
        
        while time.time() < end_time:
            if process.poll() is not None:
                # Process has terminated
                break
            time.sleep(1)
        
        # If still running, terminate gracefully
        if process.poll() is None:
            print("Timeout reached, terminating bot...")
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                print("Force killing bot process...")
                process.kill()
                process.wait()
        
        exit_code = process.returncode or 0
        print(f"Bot finished with exit code: {exit_code}")
        
        # Check if we have any logs
        session_dir = Path(os.getenv("AURORA_SESSION_DIR", "logs"))
        events_file = session_dir / "aurora_events.jsonl"
        if events_file.exists():
            print(f"Events logged to: {events_file}")
        else:
            print("No events file found - check configuration")
            
        return exit_code
        
    except KeyboardInterrupt:
        print("Interrupted by user")
        if 'process' in locals() and process.poll() is None:
            process.terminate()
            process.wait()
        return 130
    except Exception as e:
        print(f"Error running bot: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())