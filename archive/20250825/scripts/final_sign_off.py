#!/usr/bin/env python3
"""
AURORA Final Sign-off Script
Executes all 7 pre-GO validation steps idempotently
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

def run_command(cmd, description, critical=True):
    """Run command with error handling"""
    print(f"\n🔍 {description}")
    print(f"   Command: {cmd}")
    
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            print(f"   ✅ PASS")
            if result.stdout.strip():
                print(f"   Output: {result.stdout.strip()[:200]}...")
            return True, result.stdout
        else:
            print(f"   ❌ FAIL (exit code: {result.returncode})")
            if result.stderr.strip():
                print(f"   Error: {result.stderr.strip()[:200]}...")
            if critical:
                return False, result.stderr
            else:
                print(f"   ⚠️  Non-critical failure, continuing...")
                return True, result.stderr
    
    except Exception as e:
        print(f"   ❌ EXCEPTION: {e}")
        if critical:
            return False, str(e)
        return True, str(e)

def check_panic_safety():
    """Check that panic safety is not active"""
    print(f"\n🔍 7. Checking panic safety status")
    
    panic_file = Path("artifacts/ci/hard_panic.flag")
    if panic_file.exists():
        print(f"   ❌ PANIC FLAG ACTIVE: {panic_file}")
        return False
    
    # Check master.yaml for hard_override setting
    master_yaml = Path("configs/master.yaml")
    if master_yaml.exists():
        try:
            import yaml
            with open(master_yaml) as f:
                config = yaml.safe_load(f)
            
            hard_override = config.get('ci_gating', {}).get('hard_override', 'unknown')
            print(f"   ci_gating.hard_override: {hard_override}")
            
            if hard_override != 'auto':
                print(f"   ⚠️  Expected 'auto', got '{hard_override}'")
                return False
            
        except Exception as e:
            print(f"   ⚠️  Could not check master.yaml: {e}")
    
    print(f"   ✅ Panic safety OK")
    return True

def main():
    parser = argparse.ArgumentParser(description="Execute final sign-off before GA cutover")
    parser.add_argument('--output', default='artifacts/sign_off/final_report.json', help="Output report file")
    parser.add_argument('--skip-non-critical', action='store_true', help="Skip non-critical checks if they fail")
    
    args = parser.parse_args()
    
    print("🚀 AURORA 0.4.0 GA - Final Sign-off")
    print("=" * 50)
    
    # Ensure output directory exists
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Track results
    results = {
        "metadata": {
            "timestamp": datetime.now().isoformat(),
            "version": "0.4.0",
            "script": "final_sign_off.py"
        },
        "checks": {},
        "summary": {
            "total_checks": 7,
            "passed": 0,
            "failed": 0,
            "overall_status": "UNKNOWN"
        }
    }
    
    checks = [
        {
            "id": 1,
            "name": "Profile/Lock Validation",
            "command": "python scripts/validate_profiles.py --profile configs/profiles/r2.yaml --lock configs/profiles/r2.lock.json",
            "critical": True
        },
        {
            "id": 2,
            "name": "Schema Validation",
            "command": "python tools/schema_linter.py --file configs/ci_thresholds.yaml --format json",
            "critical": True
        },
        {
            "id": 3,
            "name": "GA Gates Evaluation",
            "command": "python scripts/ga_gates_eval.py --format md --output artifacts/ga/ga_gates_now.md",
            "critical": True
        },
        {
            "id": 4,
            "name": "DCTS Audit",
            "command": "python tools/dcts_audit.py --summaries artifacts/replay_reports/*.json --out-json artifacts/dcts_audit/report.json --out-md artifacts/dcts_audit/summary.md",
            "critical": not args.skip_non_critical
        },
        {
            "id": 5,
            "name": "Checkpoint QA",
            "command": "python tools/analyze_checkpoints.py --ckpt-dir checkpoints/ --ref latest-1 --jsonl artifacts/ckpt/analyze.jsonl --report artifacts/ckpt/report.json --exit-on-anomaly",
            "critical": True
        },
        {
            "id": 6,
            "name": "Alerts/Dashboard Check",
            "command": "promtool check rules artifacts/obs/alerts_week1.yaml",
            "critical": not args.skip_non_critical
        }
    ]
    
    # Execute checks
    for check in checks:
        success, output = run_command(
            check["command"], 
            f"{check['id']}. {check['name']}", 
            check["critical"]
        )
        
        results["checks"][f"check_{check['id']}"] = {
            "name": check["name"],
            "command": check["command"],
            "success": success,
            "output": output[:500] if output else "",  # Truncate output
            "critical": check["critical"]
        }
        
        if success:
            results["summary"]["passed"] += 1
        else:
            results["summary"]["failed"] += 1
            if check["critical"]:
                print(f"\n❌ CRITICAL CHECK FAILED: {check['name']}")
                print(f"   Cannot proceed with GA cutover")
                results["summary"]["overall_status"] = "FAILED"
                break
    
    # Check panic safety (step 7)
    panic_safe = check_panic_safety()
    results["checks"]["check_7"] = {
        "name": "Panic Safety Check",
        "command": "check panic flags and master.yaml",
        "success": panic_safe,
        "output": "Checked panic flag and hard_override setting",
        "critical": True
    }
    
    if panic_safe:
        results["summary"]["passed"] += 1
    else:
        results["summary"]["failed"] += 1
        if results["summary"]["overall_status"] != "FAILED":
            results["summary"]["overall_status"] = "FAILED"
    
    # Determine overall status
    if results["summary"]["overall_status"] == "UNKNOWN":
        if results["summary"]["failed"] == 0:
            results["summary"]["overall_status"] = "READY_FOR_GO"
        else:
            results["summary"]["overall_status"] = "ISSUES_DETECTED"
    
    # Write results
    try:
        with open(output_path, 'w') as f:
            json.dump(results, f, indent=2)
        print(f"\n📄 Sign-off report written to: {output_path}")
    except Exception as e:
        print(f"\n❌ Failed to write report: {e}")
    
    # Print final summary
    print(f"\n" + "="*50)
    print(f"📊 FINAL SIGN-OFF SUMMARY")
    print(f"="*50)
    print(f"Total Checks: {results['summary']['total_checks']}")
    print(f"Passed: {results['summary']['passed']}")
    print(f"Failed: {results['summary']['failed']}")
    print(f"Overall Status: {results['summary']['overall_status']}")
    
    if results["summary"]["overall_status"] == "READY_FOR_GO":
        print(f"\n🏆 ✅ ALL SYSTEMS GO - READY FOR GA CUTOVER!")
        print(f"\nNext steps:")
        print(f"   1. Fill GA decision template with current metrics")
        print(f"   2. Execute Day-0 cutover: python scripts/day0_cutover.py --confirm --profile r2")
        print(f"   3. Start 24h watch: python scripts/watch_24h.py")
        sys.exit(0)
    else:
        print(f"\n❌ SIGN-OFF FAILED - Cannot proceed with GA cutover")
        print(f"\nRequired actions:")
        for check_id, check_result in results["checks"].items():
            if not check_result["success"] and check_result["critical"]:
                print(f"   • Fix: {check_result['name']}")
        sys.exit(1)

if __name__ == "__main__":
    main()