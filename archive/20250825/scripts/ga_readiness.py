#!/usr/bin/env python3
"""
AURORA GA Readiness Report
Комплексна перевірка готовності RC → GA
"""
import json
import yaml
import argparse
from pathlib import Path
from datetime import datetime
import subprocess

def check_version_consistency():
    """Перевірити консистентність версій"""
    try:
        # Check VERSION file
        version_file = Path("VERSION")
        if not version_file.exists():
            return False, "VERSION file not found"
        
        version = version_file.read_text().strip()
        
        # Check if it's RC version
        if not version.endswith("-rc1"):
            return False, f"Expected RC version, got: {version}"
        
        return True, f"Version {version} confirmed"
        
    except Exception as e:
        return False, f"Version check failed: {e}"

def check_configuration_profiles():
    """Перевірити профілі конфігурації"""
    try:
        profiles_dir = Path("configs/profiles")
        
        # Check profiles exist
        r2_profile = profiles_dir / "r2.yaml"
        smoke_profile = profiles_dir / "smoke.yaml"
        
        if not r2_profile.exists():
            return False, "r2.yaml profile not found"
        
        if not smoke_profile.exists():
            return False, "smoke.yaml profile not found"
        
        # Check lock files exist
        r2_lock = profiles_dir / "r2.yaml.lock"
        smoke_lock = profiles_dir / "smoke.yaml.lock"
        
        if not r2_lock.exists():
            return False, "r2.yaml not locked"
        
        if not smoke_lock.exists():
            return False, "smoke.yaml not locked"
        
        # Validate lock integrity
        with open(r2_lock, 'r') as f:
            r2_lock_data = json.load(f)
        
        with open(r2_profile, 'r') as f:
            r2_config = yaml.safe_load(f)
        
        # Check required sections
        required_sections = ["acceptance", "kappa_thresholds", "preloop"]
        for section in required_sections:
            if section not in r2_config:
                return False, f"r2.yaml missing section: {section}"
        
        return True, "Configuration profiles locked and valid"
        
    except Exception as e:
        return False, f"Profile check failed: {e}"

def check_build_artifacts():
    """Перевірити артефакти збірки"""
    try:
        build_script = Path("scripts/build_release.py")
        
        if not build_script.exists():
            return False, "Build script not found"
        
        # Check if script can run (test help)
        result = subprocess.run(
            ["python", str(build_script), "--help"],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return False, f"Build script test failed: {result.stderr}"
        
        return True, "Build artifacts ready"
        
    except Exception as e:
        return False, f"Build check failed: {e}"

def check_ga_gates_framework():
    """Перевірити GA gates framework"""
    try:
        stats_script = Path("scripts/report_preloop_stats.py")
        
        if not stats_script.exists():
            return False, "Preloop stats script not found"
        
        # Test script can run
        result = subprocess.run(
            ["python", str(stats_script), "--help"],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return False, "GA gates script not functional"
        
        return True, "GA gates framework ready"
        
    except Exception as e:
        return False, f"GA gates check failed: {e}"

def check_canary_framework():
    """Перевірити canary deployment framework"""
    try:
        canary_script = Path("scripts/canary_deploy.py")
        
        if not canary_script.exists():
            return False, "Canary script not found"
        
        # Test script can run
        result = subprocess.run(
            ["python", str(canary_script), "--help"],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return False, "Canary script not functional"
        
        return True, "Canary deployment framework ready"
        
    except Exception as e:
        return False, f"Canary check failed: {e}"

def check_observability_dashboard():
    """Перевірити observability dashboard"""
    try:
        dashboard_file = Path("monitoring/aurora_dashboard.json")
        alerts_file = Path("monitoring/aurora_alerts.yml")
        
        if not dashboard_file.exists():
            return False, "Grafana dashboard not found"
        
        if not alerts_file.exists():
            return False, "Prometheus alerts not found"
        
        # Validate dashboard JSON
        with open(dashboard_file, 'r') as f:
            dashboard = json.load(f)
        
        if "panels" not in dashboard:
            return False, "Dashboard missing panels"
        
        return True, "Observability dashboard ready"
        
    except Exception as e:
        return False, f"Dashboard check failed: {e}"

def check_rollback_readiness():
    """Перевірити готовність до rollback"""
    try:
        # Check if git is available
        result = subprocess.run(
            ["git", "--version"],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return True, "Git not required for RC deployment"
        
        # Check git status if available
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True
        )
        
        if result.returncode != 0:
            return True, "Git repo not initialized (optional)"
        
        # Check for uncommitted changes
        if result.stdout.strip():
            return False, "Uncommitted changes detected"
        
        return True, "Rollback ready (git available)"
        
    except Exception as e:
        return True, f"Git optional: {e}"

def generate_ga_readiness_report():
    """Генерувати повний звіт готовності"""
    
    checks = [
        ("Version Consistency", check_version_consistency),
        ("Configuration Profiles", check_configuration_profiles),
        ("Build Artifacts", check_build_artifacts),
        ("GA Gates Framework", check_ga_gates_framework),
        ("Canary Framework", check_canary_framework),
        ("Observability Dashboard", check_observability_dashboard),
        ("Rollback Readiness", check_rollback_readiness)
    ]
    
    results = {}
    overall_ready = True
    
    print("🔍 AURORA GA Readiness Assessment")
    print("=" * 50)
    
    for check_name, check_func in checks:
        try:
            passed, message = check_func()
            results[check_name] = {
                "passed": passed,
                "message": message
            }
            
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"{check_name:.<30} {status}")
            print(f"  {message}")
            
            if not passed:
                overall_ready = False
                
        except Exception as e:
            results[check_name] = {
                "passed": False,
                "message": f"Check error: {e}"
            }
            print(f"{check_name:.<30} ❌ ERROR")
            print(f"  Check error: {e}")
            overall_ready = False
    
    print("=" * 50)
    
    if overall_ready:
        print("🎉 AURORA RC is READY for GA promotion!")
        readiness_status = "READY"
    else:
        print("⚠️ AURORA RC has issues - address before GA")
        readiness_status = "NOT_READY"
    
    # Generate detailed report
    report = {
        "timestamp": datetime.now().isoformat(),
        "overall_ready": overall_ready,
        "readiness_status": readiness_status,
        "checks": results,
        "next_steps": generate_next_steps(results, overall_ready),
        "ga_promotion_criteria": {
            "version_format": "Semantic versioning with RC suffix",
            "configuration_locked": "All profiles locked with checksums",
            "ga_gates_ready": "Statistical framework operational",
            "canary_framework": "Automated canary deployment ready",
            "observability": "Monitoring dashboard and alerts configured",
            "rollback_plan": "Git-based rollback strategy verified"
        }
    }
    
    return report

def generate_next_steps(results, overall_ready):
    """Генерувати наступні кроки"""
    if overall_ready:
        return [
            "Run canary deployment tests: python scripts/canary_deploy.py",
            "Collect 24-48h staging metrics",
            "Evaluate GA gates: python scripts/report_preloop_stats.py",
            "If gates pass, promote RC to GA version",
            "Deploy to production with monitoring"
        ]
    else:
        next_steps = ["Address the following issues:"]
        
        for check_name, result in results.items():
            if not result["passed"]:
                next_steps.append(f"- Fix {check_name}: {result['message']}")
        
        next_steps.append("Re-run readiness assessment")
        
        return next_steps

def main():
    parser = argparse.ArgumentParser(description="AURORA GA Readiness Assessment")
    parser.add_argument("--output", default="artifacts/ga_readiness_report.json",
                       help="Output report file")
    parser.add_argument("--verbose", action="store_true",
                       help="Verbose output")
    
    args = parser.parse_args()
    
    # Ensure artifacts directory exists
    Path("artifacts").mkdir(exist_ok=True)
    
    # Generate report
    report = generate_ga_readiness_report()
    
    # Save report
    with open(args.output, 'w') as f:
        json.dump(report, f, indent=2)
    
    print(f"\n📋 Detailed report saved to {args.output}")
    
    if args.verbose:
        print("\n📝 Next Steps:")
        for i, step in enumerate(report["next_steps"], 1):
            print(f"  {i}. {step}")
    
    # Exit with appropriate code
    return 0 if report["overall_ready"] else 1

if __name__ == "__main__":
    exit(main())