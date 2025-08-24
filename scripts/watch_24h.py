#!/usr/bin/env python3
"""
AURORA 24h Watch Monitor
Hourly GA gates monitoring for first 24h post-GA
"""
import json
import subprocess
import argparse
from pathlib import Path
from datetime import datetime, timedelta

def run_monitoring_command(cmd, description):
    """Run monitoring command and capture results"""
    print(f"\n📊 {description}")
    print(f"$ {cmd}")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=300)
        
        success = result.returncode == 0
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status}: {description}")
        
        if result.stdout:
            print(result.stdout[-500:])  # Last 500 chars
        
        if not success and result.stderr:
            print(f"Error: {result.stderr[-200:]}")
        
        return success, result.returncode, result.stdout, result.stderr
        
    except subprocess.TimeoutExpired:
        print(f"⏰ TIMEOUT: {description}")
        return False, -1, "", "Command timeout"
    except Exception as e:
        print(f"💥 ERROR: {description} - {e}")
        return False, -1, "", str(e)

def watch_24h_cycle():
    """Execute one 24h watch cycle"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    watch_dir = Path(f"artifacts/ga/watch24h")
    watch_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🔍 24h Watch Cycle - {timestamp}")
    print("=" * 50)
    
    results = {
        "timestamp": timestamp,
        "cycle_start": datetime.now().isoformat(),
        "checks": {}
    }
    
    # CHECK 1: GA Gates Evaluation
    success, code, stdout, stderr = run_monitoring_command(
        f"python scripts/ga_gates_eval.py --format json --output {watch_dir}/ga_gates_{timestamp}.json",
        "GA Gates Evaluation"
    )
    results["checks"]["ga_gates"] = {
        "success": success,
        "exit_code": code,
        "output_file": f"{watch_dir}/ga_gates_{timestamp}.json"
    }
    
    # CHECK 2: DCTS Audit (if replay reports available)
    replay_reports = list(Path("artifacts/replay_reports").glob("*.json")) if Path("artifacts/replay_reports").exists() else []
    
    if replay_reports:
        success, code, stdout, stderr = run_monitoring_command(
            f"python tools/dcts_audit.py --summaries artifacts/replay_reports/*.json --out-json {watch_dir}/dcts_audit_{timestamp}.json --out-md {watch_dir}/dcts_audit_{timestamp}.md",
            "DCTS Robustness Audit"
        )
        results["checks"]["dcts_audit"] = {
            "success": success,
            "exit_code": code,
            "reports_found": len(replay_reports)
        }
    else:
        print("⚠️ SKIP: DCTS Audit - No replay reports found")
        results["checks"]["dcts_audit"] = {
            "success": None,
            "skip_reason": "No replay reports"
        }
    
    # CHECK 3: Checkpoint Analysis (if checkpoints available)
    if Path("checkpoints").exists():
        success, code, stdout, stderr = run_monitoring_command(
            f"python scripts/analyze_checkpoints.py --ckpt-dir checkpoints/ --report {watch_dir}/ckpt_analysis_{timestamp}.json",
            "Checkpoint Quality Analysis"
        )
        results["checks"]["checkpoint_analysis"] = {
            "success": success,
            "exit_code": code
        }
    else:
        print("⚠️ SKIP: Checkpoint Analysis - No checkpoints directory")
        results["checks"]["checkpoint_analysis"] = {
            "success": None,
            "skip_reason": "No checkpoints directory"
        }
    
    # CHECK 4: Profile Lock Integrity
    success, code, stdout, stderr = run_monitoring_command(
        "python scripts/mk_profile_lock.py --in configs/profiles/r2.yaml --validate",
        "Profile Lock Integrity Check"
    )
    results["checks"]["profile_lock"] = {
        "success": success,
        "exit_code": code
    }
    
    # CHECK 5: Panic Flag Status
    panic_flag = Path("artifacts/ci/hard_panic.flag")
    panic_exists = panic_flag.exists()
    
    if panic_exists:
        print("🚨 PANIC FLAG DETECTED - Hard gating disabled!")
        results["checks"]["panic_flag"] = {
            "success": False,
            "panic_active": True,
            "flag_path": str(panic_flag)
        }
    else:
        print("✅ No panic flag - Hard gating active")
        results["checks"]["panic_flag"] = {
            "success": True,
            "panic_active": False
        }
    
    # Evaluate overall health
    critical_checks = ["ga_gates", "profile_lock", "panic_flag"]
    critical_failures = []
    
    for check in critical_checks:
        if check in results["checks"] and not results["checks"][check]["success"]:
            critical_failures.append(check)
    
    overall_healthy = len(critical_failures) == 0
    
    results["overall_healthy"] = overall_healthy
    results["critical_failures"] = critical_failures
    results["cycle_end"] = datetime.now().isoformat()
    
    # Save results
    with open(watch_dir / f"watch_cycle_{timestamp}.json", "w") as f:
        json.dump(results, f, indent=2)
    
    # Print summary
    print(f"\n📋 24h Watch Summary - {timestamp}")
    print(f"Overall Health: {'✅ HEALTHY' if overall_healthy else '❌ UNHEALTHY'}")
    
    if critical_failures:
        print(f"Critical Failures: {critical_failures}")
        print("🚨 IMMEDIATE ATTENTION REQUIRED")
    
    for check, result in results["checks"].items():
        if result["success"] is None:
            status = "⚠️ SKIP"
        elif result["success"]:
            status = "✅ PASS"
        else:
            status = "❌ FAIL"
        print(f"  {check}: {status}")
    
    return overall_healthy

def main():
    parser = argparse.ArgumentParser(description="AURORA 24h Watch Monitor")
    parser.add_argument("--continuous", action="store_true", help="Run continuous hourly monitoring")
    parser.add_argument("--hours", type=int, default=24, help="Number of hours to monitor")
    
    args = parser.parse_args()
    
    if args.continuous:
        print(f"🔄 Starting continuous 24h watch for {args.hours} hours")
        
        cycles_completed = 0
        healthy_cycles = 0
        
        try:
            while cycles_completed < args.hours:
                healthy = watch_24h_cycle()
                cycles_completed += 1
                
                if healthy:
                    healthy_cycles += 1
                
                if cycles_completed < args.hours:
                    print(f"\n⏰ Sleeping 1 hour... (cycle {cycles_completed}/{args.hours})")
                    import time
                    time.sleep(3600)  # 1 hour
            
            print(f"\n🎯 24h Watch Completed!")
            print(f"Cycles: {cycles_completed}")
            print(f"Healthy: {healthy_cycles} ({healthy_cycles/cycles_completed:.1%})")
            
            if healthy_cycles == cycles_completed:
                print("🎉 ALL CYCLES HEALTHY - GA promotion successful!")
                return 0
            else:
                print("⚠️ Some cycles had issues - review logs")
                return 1
                
        except KeyboardInterrupt:
            print("\n🛑 Watch interrupted by user")
            return 130
    else:
        # Single cycle
        healthy = watch_24h_cycle()
        return 0 if healthy else 1

if __name__ == "__main__":
    import sys
    sys.exit(main())