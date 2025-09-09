#!/usr/bin/env python3
"""
Aurora canary runner
===================

Canary test runner for Aurora system validation.
Runs trading bot for specified duration with monitoring and validation.

Usage:
    python tools/run_canary.py --minutes 60 --runner-config profiles/testnet_aggressive.yaml
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


def main():
    parser = argparse.ArgumentParser(description="Aurora canary runner")
    parser.add_argument("--minutes", type=int, default=60, help="Duration in minutes")
    parser.add_argument("--runner-config", help="Runner configuration file path")
    args = parser.parse_args()

    print(f"Starting Aurora canary run for {args.minutes} minutes")
    
    # Set environment for canary mode
    mode = os.getenv("AURORA_MODE", "testnet")
    print(f"Running in mode: {mode}")
    
    # Prepare runner command
    runner_cmd = [
        sys.executable, 
        "-m", 
        "skalp_bot.runner.run_live_aurora"
    ]
    
    if args.runner_config:
        runner_cmd.extend(["--config", args.runner_config])
    
    # Set base URL to match API port
    base_url = os.getenv("AURORA_BASE_URL", "http://127.0.0.1:8000")
    runner_cmd.extend(["--base-url", base_url])
    
    print(f"Starting canary bot with command: {' '.join(runner_cmd)}")
    
    # Run the trading bot
    try:
        # Calculate timeout with buffer
        timeout_seconds = args.minutes * 60 + 60
        
        # Start the process
        process = subprocess.Popen(
            runner_cmd,
            cwd=str(ROOT),
            env=os.environ.copy()
        )
        
        # Monitor the process with timeout
        start_time = time.time()
        end_time = start_time + (args.minutes * 60)
        
        while time.time() < end_time:
            if process.poll() is not None:
                # Process has terminated
                break
            time.sleep(5)  # Check every 5 seconds
        
        # If still running, terminate gracefully
        if process.poll() is None:
            print("Timeout reached, terminating canary...")
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                print("Force killing canary process...")
                process.kill()
                process.wait()
        
        exit_code = process.returncode or 0
        print(f"Canary finished with exit code: {exit_code}")
        
        # Check for events and logs
        session_dir = Path(os.getenv("AURORA_SESSION_DIR", "logs"))
        events_file = session_dir / "aurora_events.jsonl"
        if events_file.exists():
            print(f"Canary events logged to: {events_file}")
            # Count events as basic validation
            try:
                with events_file.open('r') as f:
                    event_count = sum(1 for _ in f)
                print(f"Total events generated: {event_count}")
            except Exception:
                pass
        else:
            print("Warning: No events file found")
            
        return exit_code
        
    except KeyboardInterrupt:
        print("Canary interrupted by user")
        if 'process' in locals() and process.poll() is None:
            process.terminate()
            process.wait()
        return 130
    except Exception as e:
        print(f"Error running canary: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())