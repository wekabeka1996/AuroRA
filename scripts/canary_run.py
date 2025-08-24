#!/usr/bin/env python3
"""
Canary Runner v1.0 - Production-ready canary testing
Executes multiple short runs with specified profile and gating
"""
import json
import yaml
import subprocess
import argparse
from pathlib import Path
from datetime import datetime
import time
import statistics

def run_single_canary(profile_path: str, run_id: int, gating: str = "soft") -> dict:
    """Run single canary test"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    cmd = [
        "python", "scripts/run_r0.py",
        "--config", profile_path,
        "--mode", "r2",
        "--minutes", "0.6",
        "--r2-preloop-max-ticks", "3",
        "--duration-applies-to", "main",
        "--no-auto-summary=false"
    ]
    
    if gating == "soft":
        cmd.extend(["--ci-gating", "soft"])
    elif gating == "hard":
        cmd.extend(["--ci-gating", "hard"])
    
    print(f"🕊️ Running canary {run_id}: {' '.join(cmd)}")
    
    start_time = time.time()
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        duration = time.time() - start_time
        
        success = result.returncode == 0
        
        # Look for summary file
        summary_pattern = f"summary_r2_{timestamp}*.json"
        summary_files = list(Path("runs").glob(f"**/summary_*.json"))
        
        latest_summary = None
        if summary_files:
            # Get most recent summary
            latest_summary = max(summary_files, key=lambda p: p.stat().st_mtime)
        
        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "success": success,
            "exit_code": result.returncode,
            "duration": duration,
            "summary_file": str(latest_summary) if latest_summary else None,
            "stdout": result.stdout[-1000:],  # Last 1000 chars
            "stderr": result.stderr[-500:] if result.stderr else ""
        }
        
    except subprocess.TimeoutExpired:
        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "success": False,
            "exit_code": -1,
            "duration": time.time() - start_time,
            "summary_file": None,
            "stdout": "",
            "stderr": "Timeout after 120s"
        }
    except Exception as e:
        return {
            "run_id": run_id,
            "timestamp": timestamp,
            "success": False,
            "exit_code": -1,
            "duration": time.time() - start_time,
            "summary_file": None,
            "stdout": "",
            "stderr": str(e)
        }

def analyze_canary_health(summary_file: str) -> dict:
    """Analyze health of single canary run"""
    if not summary_file or not Path(summary_file).exists():
        return {"healthy": False, "reason": "No summary file"}
    
    try:
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        # Health checks
        r2_main = summary.get("r2_main_loop", {})
        r2_preloop = summary.get("r2_preloop", {})
        
        decisions = r2_main.get("decisions", 0)
        execution_decisions = r2_main.get("execution_decisions", {})
        exit_kind = r2_preloop.get("exit_kind", "")
        skip_reasons = r2_preloop.get("skip_reasons", {})
        zero_budget = skip_reasons.get("zero_budget", 0)
        
        health_checks = {
            "has_decisions": decisions > 0,
            "has_executions": len(execution_decisions) > 0,
            "clean_exit": exit_kind == "exit",
            "no_zero_budget": zero_budget == 0
        }
        
        healthy = all(health_checks.values())
        
        return {
            "healthy": healthy,
            "health_checks": health_checks,
            "decisions": decisions,
            "executions": len(execution_decisions),
            "exit_kind": exit_kind,
            "zero_budget": zero_budget
        }
        
    except Exception as e:
        return {"healthy": False, "reason": f"Analysis failed: {e}"}

def run_canary_sequence(profile_path: str, num_runs: int, gating: str) -> dict:
    """Run sequence of canary tests"""
    print(f"🚀 Starting canary sequence: {num_runs} runs with {gating} gating")
    print(f"📋 Profile: {profile_path}")
    
    results = []
    health_results = []
    
    for i in range(num_runs):
        print(f"\n--- Canary Run {i+1}/{num_runs} ---")
        
        # Run canary
        result = run_single_canary(profile_path, i+1, gating)
        results.append(result)
        
        # Analyze health if successful
        if result["success"] and result["summary_file"]:
            health = analyze_canary_health(result["summary_file"])
            health_results.append(health)
            
            health_status = "✅ HEALTHY" if health["healthy"] else "⚠️ UNHEALTHY"
            print(f"   Health: {health_status}")
            
            if not health["healthy"]:
                if "reason" in health:
                    print(f"     Reason: {health['reason']}")
                else:
                    failed_checks = [k for k, v in health.get("health_checks", {}).items() if not v]
                    print(f"     Failed checks: {failed_checks}")
        else:
            print(f"   ❌ Run failed: exit_code={result['exit_code']}")
            health_results.append({"healthy": False, "reason": "Run failed"})
        
        # Small delay between runs
        if i < num_runs - 1:
            print("   ⏳ Waiting 10s...")
            time.sleep(10)
    
    return {
        "run_results": results,
        "health_results": health_results
    }

def evaluate_canary_results(run_results: list, health_results: list) -> dict:
    """Evaluate overall canary sequence results"""
    total_runs = len(run_results)
    successful_runs = sum(1 for r in run_results if r["success"])
    healthy_runs = sum(1 for h in health_results if h.get("healthy", False))
    
    success_rate = successful_runs / total_runs if total_runs > 0 else 0
    health_rate = healthy_runs / total_runs if total_runs > 0 else 0
    
    # Calculate average duration
    durations = [r["duration"] for r in run_results if r["success"]]
    avg_duration = statistics.mean(durations) if durations else 0
    
    # Success criteria: at least 70% success and health rate
    success_threshold = 0.7
    health_threshold = 0.7
    
    passed = success_rate >= success_threshold and health_rate >= health_threshold
    
    evaluation = {
        "total_runs": total_runs,
        "successful_runs": successful_runs,
        "healthy_runs": healthy_runs,
        "success_rate": success_rate,
        "health_rate": health_rate,
        "avg_duration": avg_duration,
        "success_threshold": success_threshold,
        "health_threshold": health_threshold,
        "overall_passed": passed,
        "status": "PASS" if passed else "FAIL"
    }
    
    return evaluation

def main():
    parser = argparse.ArgumentParser(description="Canary Runner v1.0")
    parser.add_argument("--profile", required=True, help="Profile YAML file")
    parser.add_argument("--runs", type=int, default=10, help="Number of canary runs")
    parser.add_argument("--gating", choices=["soft", "hard", "none"], default="soft",
                       help="CI gating mode")
    parser.add_argument("--output", default="artifacts/canary_results.json",
                       help="Output results file")
    
    args = parser.parse_args()
    
    # Ensure artifacts directory exists
    Path("artifacts").mkdir(exist_ok=True)
    
    # Validate profile exists
    if not Path(args.profile).exists():
        print(f"❌ Profile not found: {args.profile}")
        return 1
    
    print(f"🕊️ AURORA Canary Runner v1.0")
    print(f"Profile: {args.profile}")
    print(f"Runs: {args.runs}")
    print(f"Gating: {args.gating}")
    
    try:
        # Run canary sequence
        sequence_results = run_canary_sequence(args.profile, args.runs, args.gating)
        
        # Evaluate results
        evaluation = evaluate_canary_results(
            sequence_results["run_results"],
            sequence_results["health_results"]
        )
        
        # Create final report
        report = {
            "timestamp": datetime.now().isoformat(),
            "config": {
                "profile": args.profile,
                "runs": args.runs,
                "gating": args.gating
            },
            "evaluation": evaluation,
            "run_results": sequence_results["run_results"],
            "health_results": sequence_results["health_results"]
        }
        
        # Save report
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        
        # Print summary
        print(f"\n📊 Canary Results Summary:")
        print(f"  Total runs: {evaluation['total_runs']}")
        print(f"  Successful: {evaluation['successful_runs']} ({evaluation['success_rate']:.1%})")
        print(f"  Healthy: {evaluation['healthy_runs']} ({evaluation['health_rate']:.1%})")
        print(f"  Avg duration: {evaluation['avg_duration']:.1f}s")
        print(f"  Status: {'✅ PASS' if evaluation['overall_passed'] else '❌ FAIL'}")
        
        print(f"\n✅ Results saved to {args.output}")
        
        return 0 if evaluation['overall_passed'] else 1
        
    except Exception as e:
        print(f"❌ Canary sequence failed: {e}")
        return 1

if __name__ == "__main__":
    exit(main())