#!/usr/bin/env python3
"""
AURORA Day-0 GA Cutover Playbook
Idempotent production cutover with exit code checks
"""
import os
import sys
import subprocess
import json
from pathlib import Path
from datetime import datetime

def run_command(cmd, description, critical=True):
    """Run command with exit code validation"""
    print(f"\n🔄 {description}")
    print(f"$ {cmd}")
    
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    
    if result.stdout:
        print(result.stdout)
    if result.stderr:
        print(result.stderr)
    
    if result.returncode != 0:
        if critical:
            print(f"❌ CRITICAL FAILURE: {description}")
            print(f"Exit code: {result.returncode}")
            print("🛑 STOPPING CUTOVER - Fix and retry")
            sys.exit(result.returncode)
        else:
            print(f"⚠️ WARNING: {description} failed with code {result.returncode}")
    else:
        print(f"✅ SUCCESS: {description}")
    
    return result.returncode == 0

def day_0_cutover():
    """Execute Day-0 GA Cutover"""
    print("🚀 AURORA Day-0 GA Cutover Starting")
    print("=" * 50)
    
    # STEP 1: Version and Tag
    print("\n📋 STEP 1: Version and Tag")
    
    # Update VERSION file
    with open("VERSION", "w") as f:
        f.write("0.4.0\n")
    print("✅ VERSION updated to 0.4.0")
    
    # Create git tag (non-critical if git not available)
    run_command(
        'git tag -a v0.4.0 -m "AURORA GA 0.4.0"',
        "Create git tag v0.4.0",
        critical=False
    )
    
    # STEP 2: Profile Lock Validation (CRITICAL)
    print("\n🔒 STEP 2: Profile Lock Validation (CRITICAL)")
    
    success = run_command(
        "python scripts/mk_profile_lock.py --in configs/profiles/r2.yaml --validate",
        "Validate r2 profile lock",
        critical=True
    )
    
    success = run_command(
        "python scripts/validate_profiles.py --profile configs/profiles/r2.yaml --lock configs/profiles/r2.lock.json",
        "Cross-validate r2 profile integrity",
        critical=True
    )
    
    # STEP 3: Hard-gating Mode Configuration
    print("\n⚡ STEP 3: Hard-gating Mode Configuration")
    
    # Check no panic flag exists
    panic_flag = Path("artifacts/ci/hard_panic.flag")
    if panic_flag.exists():
        print("❌ CRITICAL: Panic flag exists - remove before cutover")
        print(f"File: {panic_flag}")
        sys.exit(3)
    else:
        print("✅ No panic flag found")
    
    # Verify hard_override setting (would need config manipulation)
    print("⚠️ MANUAL CHECK: Verify master.yaml has ci_gating.hard_override: auto")
    
    # STEP 4: Monitoring Setup  
    print("\n📊 STEP 4: Monitoring Setup")
    
    # Check alerts configuration
    alerts_file = Path("monitoring/aurora_alerts.yml")
    if alerts_file.exists():
        run_command(
            f"python -c \"import yaml; yaml.safe_load(open('{alerts_file}'))\"",
            "Validate alerts YAML syntax",
            critical=True
        )
    
    # Check dashboard  
    dashboard_file = Path("monitoring/aurora_dashboard.json")
    if dashboard_file.exists():
        run_command(
            f"python -c \"import json; json.load(open('{dashboard_file}'))\"",
            "Validate dashboard JSON syntax",
            critical=True
        )
    
    print("✅ Monitoring configuration validated")
    print("⚠️ MANUAL: Import dashboard to Grafana and enable alerts")
    
    # STEP 5: Smoke Test
    print("\n💨 STEP 5: GA Readiness Smoke Test")
    
    # Ensure artifacts directory
    Path("artifacts/ga").mkdir(parents=True, exist_ok=True)
    
    # Quick canary test
    run_command(
        "python scripts/canary_run.py --profile configs/profiles/r2.yaml --runs 3 --gating=soft --output artifacts/ga/cutover_canary.json",
        "Execute cutover canary tests",
        critical=True
    )
    
    # GA Gates evaluation
    run_command(
        "python scripts/ga_gates_eval.py --format md --output artifacts/ga/cutover_gates.md",
        "Evaluate GA gates for cutover",
        critical=True
    )
    
    print("\n🎉 DAY-0 CUTOVER COMPLETED SUCCESSFULLY!")
    print("📋 Next steps:")
    print("1. Enable hard gating in master.yaml")
    print("2. Import Grafana dashboard")
    print("3. Start 24h watch monitoring")
    print("4. Review artifacts/ga/cutover_* files")

def main():
    if not Path("scripts/ga_gates_eval.py").exists():
        print("❌ GA infrastructure not found - run setup first")
        sys.exit(1)
    
    try:
        day_0_cutover()
        return 0
    except KeyboardInterrupt:
        print("\n🛑 Cutover interrupted by user")
        return 130
    except Exception as e:
        print(f"\n❌ Cutover failed with error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())