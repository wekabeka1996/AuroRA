#!/usr/bin/env python3
"""
Canary Deployment Script
Виконує коротке canary тестування RC
"""
import os
import time
import subprocess
import json
import argparse
from datetime import datetime
from pathlib import Path

def run_command(cmd, check=True, capture_output=True):
    """Виконати команду"""
    print(f"$ {cmd}")
    result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
    
    if capture_output:
        if result.stdout:
            print(result.stdout)
        if result.stderr:
            print(result.stderr)
    
    if check and result.returncode != 0:
        raise Exception(f"Command failed with exit code {result.returncode}")
    
    return result

def run_canary_test(config_base="cfg/r2.yaml", config_overlay="cfg/profiles/smoke.yaml", 
                   minutes=0.6, max_ticks=3):
    """Запустити один канарний тест"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    cmd = f"""python scripts/run_r0.py \
--config {config_base} --config {config_overlay} \
--mode r2 --minutes {minutes} --r2-preloop-max-ticks {max_ticks} \
--duration-applies-to main --no-auto-summary=false"""
    
    print(f"🕊️ Running canary test {timestamp}...")
    
    try:
        result = run_command(cmd, check=False)
        
        # Перевірити чи створений summary
        summary_files = list(Path("runs").glob(f"run_{timestamp}*/summary_*.json"))
        if summary_files:
            print(f"✅ Canary test completed with summary: {summary_files[0]}")
            return True, summary_files[0]
        else:
            print(f"⚠️ Canary test completed but no summary found")
            return False, None
            
    except Exception as e:
        print(f"❌ Canary test failed: {e}")
        return False, None

def check_canary_health(summary_file):
    """Перевірити здоров'я канарного тесту"""
    try:
        with open(summary_file, 'r') as f:
            summary = json.load(f)
        
        # Базові перевірки
        r2_main = summary.get("r2_main_loop", {})
        r2_preloop = summary.get("r2_preloop", {})
        
        checks = {
            "main_loop_started": r2_main.get("decisions", 0) > 0,
            "no_zero_budget": r2_preloop.get("skip_reasons", {}).get("zero_budget", 0) == 0,
            "preloop_exit_ok": r2_preloop.get("exit_kind") == "exit",
            "execution_decisions_exist": len(r2_main.get("execution_decisions", {})) > 0
        }
        
        passed = all(checks.values())
        
        print(f"🏥 Health checks: {'✅ HEALTHY' if passed else '⚠️ ISSUES'}")
        for check_name, result in checks.items():
            status = "✅" if result else "❌"
            print(f"  {check_name}: {status}")
        
        return passed, checks
        
    except Exception as e:
        print(f"❌ Health check failed: {e}")
        return False, {}

def run_canary_sequence(num_tests=3, delay_minutes=5):
    """Запустити послідовність канарних тестів"""
    print(f"🚀 Starting canary sequence: {num_tests} tests with {delay_minutes}min delay")
    
    results = []
    
    for i in range(num_tests):
        print(f"\n--- Canary Test {i+1}/{num_tests} ---")
        
        success, summary_file = run_canary_test()
        
        if success and summary_file:
            health_ok, health_checks = check_canary_health(summary_file)
            results.append({
                "test_id": i+1,
                "success": success,
                "health_ok": health_ok,
                "summary_file": str(summary_file),
                "health_checks": health_checks
            })
        else:
            results.append({
                "test_id": i+1,
                "success": False,
                "health_ok": False,
                "summary_file": None,
                "health_checks": {}
            })
        
        # Delay між тестами (крім останнього)
        if i < num_tests - 1:
            print(f"⏳ Waiting {delay_minutes} minutes before next test...")
            time.sleep(delay_minutes * 60)
    
    return results

def evaluate_canary_results(results):
    """Оцінити результати канарних тестів"""
    total_tests = len(results)
    successful_tests = sum(1 for r in results if r["success"])
    healthy_tests = sum(1 for r in results if r["health_ok"])
    
    success_rate = successful_tests / total_tests
    health_rate = healthy_tests / total_tests
    
    # Критерії успіху: мінімум 2/3 тестів успішні та здорові
    passed = success_rate >= 0.67 and health_rate >= 0.67
    
    report = {
        "total_tests": total_tests,
        "successful_tests": successful_tests,
        "healthy_tests": healthy_tests,
        "success_rate": success_rate,
        "health_rate": health_rate,
        "overall_passed": passed,
        "results": results
    }
    
    print(f"\n📊 Canary Results Summary:")
    print(f"  Tests run: {total_tests}")
    print(f"  Successful: {successful_tests} ({success_rate:.1%})")
    print(f"  Healthy: {healthy_tests} ({health_rate:.1%})")
    print(f"  Overall: {'✅ PASSED' if passed else '❌ FAILED'}")
    
    return report

def main():
    parser = argparse.ArgumentParser(description="Run canary deployment tests")
    parser.add_argument("--tests", type=int, default=3, help="Number of canary tests")
    parser.add_argument("--delay", type=int, default=5, help="Delay between tests (minutes)")
    parser.add_argument("--minutes", type=float, default=0.6, help="Test duration (minutes)")
    parser.add_argument("--max-ticks", type=int, default=3, help="Max preloop ticks")
    parser.add_argument("--config-base", default="cfg/r2.yaml", help="Base config file")
    parser.add_argument("--config-overlay", default="cfg/profiles/smoke.yaml", help="Overlay config")
    parser.add_argument("--output", default="artifacts/canary_report.json", help="Output report file")
    
    args = parser.parse_args()
    
    # Ensure artifacts directory exists
    Path("artifacts").mkdir(exist_ok=True)
    
    print(f"🕊️ AURORA Canary Deployment")
    print(f"Config: {args.config_base} + {args.config_overlay}")
    print(f"Tests: {args.tests} x {args.minutes}min (delay: {args.delay}min)")
    
    try:
        # Run canary sequence
        results = run_canary_sequence(args.tests, args.delay)
        
        # Evaluate results
        report = evaluate_canary_results(results)
        
        # Save report
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        print(f"✅ Canary report saved to {args.output}")
        
        # Exit with appropriate code
        if report["overall_passed"]:
            print("🎉 Canary deployment PASSED - ready for staging!")
            return 0
        else:
            print("⚠️ Canary deployment FAILED - investigate before staging")
            return 1
            
    except Exception as e:
        print(f"❌ Canary deployment error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())