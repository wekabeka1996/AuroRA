#!/usr/bin/env python3
"""
AURORA Emergency Rollback Script  
Instant rollback from GA to safe state
"""
import os
import sys
import json
import shutil
import subprocess
from pathlib import Path
from datetime import datetime

def emergency_rollback():
    """Execute emergency rollback procedure"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    print("🚨 AURORA EMERGENCY ROLLBACK INITIATED")
    print(f"Timestamp: {timestamp}")
    print("=" * 50)
    
    rollback_log = []
    
    # STEP 1: Activate panic flag
    print("\n🛑 STEP 1: Activate Panic Flag")
    
    panic_dir = Path("artifacts/ci")
    panic_dir.mkdir(parents=True, exist_ok=True)
    panic_flag = panic_dir / "hard_panic.flag"
    
    try:
        with open(panic_flag, "w") as f:
            f.write(f"EMERGENCY_ROLLBACK_{timestamp}\n")
            f.write("Hard gating disabled due to emergency rollback\n")
        
        print(f"✅ Panic flag created: {panic_flag}")
        rollback_log.append(f"Created panic flag: {panic_flag}")
        
    except Exception as e:
        print(f"❌ Failed to create panic flag: {e}")
        rollback_log.append(f"FAILED: Panic flag creation - {e}")
    
    # STEP 2: Version rollback
    print("\n⬅️ STEP 2: Version Rollback")
    
    try:
        # Rollback to RC version
        with open("VERSION", "w") as f:
            f.write("0.4.0-rc1\n")
        
        print("✅ VERSION rolled back to 0.4.0-rc1")
        rollback_log.append("VERSION rolled back to 0.4.0-rc1")
        
    except Exception as e:
        print(f"❌ Failed to rollback VERSION: {e}")
        rollback_log.append(f"FAILED: VERSION rollback - {e}")
    
    # STEP 3: Configuration rollback
    print("\n🔧 STEP 3: Configuration Rollback")
    
    # Check for RC backup bundle
    rc_bundle = Path("artifacts/release/rc_bundle.tgz")
    
    if rc_bundle.exists():
        try:
            # Extract CI thresholds from RC bundle
            result = subprocess.run([
                "tar", "-xzf", str(rc_bundle), 
                "configs/ci_thresholds.yaml", 
                "-O"
            ], capture_output=True, text=True)
            
            if result.returncode == 0:
                with open("configs/ci_thresholds.yaml", "w") as f:
                    f.write(result.stdout)
                
                print("✅ CI thresholds restored from RC bundle")
                rollback_log.append("CI thresholds restored from RC bundle")
            else:
                print("⚠️ Failed to extract from RC bundle")
                rollback_log.append("WARNING: RC bundle extraction failed")
                
        except Exception as e:
            print(f"⚠️ RC bundle rollback failed: {e}")
            rollback_log.append(f"WARNING: RC bundle rollback failed - {e}")
    else:
        print("⚠️ No RC bundle found - manual config rollback needed")
        rollback_log.append("WARNING: No RC bundle found")
    
    # STEP 4: Profile lock integrity check
    print("\n🔒 STEP 4: Profile Lock Integrity Check")
    
    try:
        result = subprocess.run([
            "python", "scripts/mk_profile_lock.py", 
            "--in", "configs/profiles/r2.yaml", 
            "--validate"
        ], capture_output=True, text=True)
        
        if result.returncode == 0:
            print("✅ Profile locks validated")
            rollback_log.append("Profile locks validated")
        else:
            print("⚠️ Profile lock validation failed")
            rollback_log.append("WARNING: Profile lock validation failed")
            
    except Exception as e:
        print(f"⚠️ Profile validation error: {e}")
        rollback_log.append(f"WARNING: Profile validation error - {e}")
    
    # STEP 5: Quick smoke test
    print("\n💨 STEP 5: Post-rollback Smoke Test")
    
    try:
        # Test basic functionality
        result = subprocess.run([
            "python", "scripts/ga_readiness.py"
        ], capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0:
            print("✅ Post-rollback smoke test passed")
            rollback_log.append("Post-rollback smoke test passed")
        else:
            print("⚠️ Post-rollback smoke test failed")
            rollback_log.append("WARNING: Post-rollback smoke test failed")
            
    except Exception as e:
        print(f"⚠️ Smoke test error: {e}")
        rollback_log.append(f"WARNING: Smoke test error - {e}")
    
    # STEP 6: Generate rollback report
    print("\n📋 STEP 6: Generate Rollback Report")
    
    rollback_report = {
        "timestamp": timestamp,
        "rollback_type": "EMERGENCY",
        "trigger": "Manual emergency rollback",
        "actions_taken": rollback_log,
        "files_modified": [
            "VERSION",
            "artifacts/ci/hard_panic.flag",
            "configs/ci_thresholds.yaml"
        ],
        "next_steps": [
            "Verify alerts stop firing",
            "Check system stability",
            "Investigate root cause",
            "Plan re-promotion when ready"
        ]
    }
    
    rollback_dir = Path("artifacts/rollback")
    rollback_dir.mkdir(parents=True, exist_ok=True)
    
    report_file = rollback_dir / f"emergency_rollback_{timestamp}.json"
    
    try:
        with open(report_file, "w") as f:
            json.dump(rollback_report, f, indent=2)
        
        print(f"✅ Rollback report saved: {report_file}")
        
    except Exception as e:
        print(f"⚠️ Failed to save rollback report: {e}")
    
    print(f"\n🎯 EMERGENCY ROLLBACK COMPLETED")
    print("=" * 50)
    print("📋 Summary:")
    
    for action in rollback_log:
        if "FAILED" in action:
            print(f"  ❌ {action}")
        elif "WARNING" in action:
            print(f"  ⚠️ {action}")
        else:
            print(f"  ✅ {action}")
    
    print(f"\n📊 Next Steps:")
    print("1. Verify panic flag effect (hard gating disabled)")
    print("2. Monitor alert reduction")
    print("3. Check system stability")
    print("4. Investigate root cause")
    print("5. Plan recovery when ready")
    
    return len([log for log in rollback_log if "FAILED" in log]) == 0

def confirm_rollback():
    """Confirm emergency rollback with user"""
    print("⚠️ EMERGENCY ROLLBACK CONFIRMATION")
    print("This will:")
    print("- Disable hard gating (panic flag)")
    print("- Rollback VERSION to RC")
    print("- Restore RC configuration")
    print("- Generate rollback report")
    
    response = input("\nType 'EMERGENCY ROLLBACK' to confirm: ")
    
    if response.strip() == "EMERGENCY ROLLBACK":
        return True
    else:
        print("❌ Rollback cancelled - exact phrase not matched")
        return False

def main():
    if "--force" in sys.argv:
        # Force mode - skip confirmation
        print("🚨 FORCE MODE: Skipping confirmation")
        confirmed = True
    else:
        confirmed = confirm_rollback()
    
    if not confirmed:
        print("🛑 Emergency rollback cancelled")
        return 1
    
    try:
        success = emergency_rollback()
        return 0 if success else 1
    except KeyboardInterrupt:
        print("\n🛑 Rollback interrupted by user")
        return 130
    except Exception as e:
        print(f"\n💥 Rollback failed with error: {e}")
        return 1

if __name__ == "__main__":
    sys.exit(main())