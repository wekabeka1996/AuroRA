#!/usr/bin/env python3
"""
AURORA Pre-loop Statistics Generator
Collects baseline metrics before GA cutover
"""

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path
import subprocess
import yaml

def run_command(cmd, capture_output=True):
    """Run shell command and return result"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=capture_output, text=True)
        return result.returncode == 0, result.stdout, result.stderr
    except Exception as e:
        return False, "", str(e)

def collect_system_stats():
    """Collect basic system statistics"""
    stats = {
        "timestamp": datetime.now().isoformat(),
        "version": "unknown",
        "system": {},
        "model": {},
        "thresholds": {},
        "health": {}
    }
    
    # Read version
    version_file = Path("VERSION")
    if version_file.exists():
        stats["version"] = version_file.read_text().strip()
    
    # System stats
    success, stdout, _ = run_command("python -c \"import psutil; print(f'{psutil.cpu_percent()},{psutil.virtual_memory().percent},{psutil.disk_usage(\".\")}')\"")
    if success and stdout:
        try:
            cpu, mem, disk_info = stdout.strip().split(',')
            stats["system"] = {
                "cpu_percent": float(cpu),
                "memory_percent": float(mem), 
                "disk_usage_gb": float(disk_info.split('(')[1].split(',')[2]) / (1024**3)
            }
        except:
            pass
    
    # Model checkpoint info
    checkpoints_dir = Path("checkpoints")
    if checkpoints_dir.exists():
        checkpoints = list(checkpoints_dir.glob("*.pt"))
        stats["model"]["checkpoint_count"] = len(checkpoints)
        if checkpoints:
            latest_ckpt = max(checkpoints, key=lambda p: p.stat().st_mtime)
            stats["model"]["latest_checkpoint"] = latest_ckpt.name
            stats["model"]["checkpoint_size_mb"] = latest_ckpt.stat().st_size / (1024*1024)
    
    # Threshold config info
    thresholds_file = Path("configs/ci_thresholds.yaml")
    if thresholds_file.exists():
        try:
            with open(thresholds_file) as f:
                threshold_data = yaml.safe_load(f)
            
            if 'thresholds' in threshold_data:
                thresh = threshold_data['thresholds']
                stats["thresholds"] = {
                    "coverage_abs_err_ema": thresh.get('coverage_abs_err_ema', {}).get('warn', 'unknown'),
                    "dcts_variance_ratio": thresh.get('dcts_variance_ratio', {}).get('warn', 'unknown'),
                    "risk_dro_factor_p05": thresh.get('risk_dro_factor_p05', {}).get('warn', 'unknown'),
                }
        except Exception as e:
            stats["thresholds"]["error"] = str(e)
    
    # Quick health check
    health_checks = [
        ("logs_exist", Path("logs").exists()),
        ("data_exists", Path("data").exists()),
        ("configs_exist", Path("configs").exists()),
        ("scripts_exist", Path("scripts").exists())
    ]
    
    for check_name, check_result in health_checks:
        stats["health"][check_name] = check_result
    
    return stats

def collect_recent_logs():
    """Collect recent log statistics"""
    log_stats = {
        "warning_count": 0,
        "error_count": 0,
        "exit_3_count": 0,
        "recent_files": []
    }
    
    logs_dir = Path("logs")
    if not logs_dir.exists():
        return log_stats
    
    # Get recent log files (last 24h)
    now = time.time()
    recent_logs = []
    
    for log_file in logs_dir.glob("*.log"):
        if now - log_file.stat().st_mtime < 24 * 3600:  # 24 hours
            recent_logs.append(log_file)
    
    log_stats["recent_files"] = [f.name for f in recent_logs[:5]]  # Top 5 recent
    
    # Count warnings/errors in recent logs
    for log_file in recent_logs:
        try:
            content = log_file.read_text()
            log_stats["warning_count"] += content.lower().count("warning")
            log_stats["error_count"] += content.lower().count("error")
            log_stats["exit_3_count"] += content.count("exit=3")
        except:
            continue
    
    return log_stats

def main():
    parser = argparse.ArgumentParser(description="Generate pre-loop statistics for GA cutover")
    parser.add_argument('--out', default='artifacts/preloop/report.json', help="Output JSON file")
    parser.add_argument('--format', choices=['json', 'yaml'], default='json', help="Output format")
    
    args = parser.parse_args()
    
    print("🔍 Collecting pre-loop statistics...")
    
    # Ensure output directory exists
    output_path = Path(args.out)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Collect statistics
    stats = collect_system_stats()
    log_stats = collect_recent_logs()
    
    # Combine results
    report = {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "generator": "preloop_stats.py",
            "version": stats.get("version", "unknown")
        },
        "system": stats["system"],
        "model": stats["model"],
        "thresholds": stats["thresholds"],
        "health": stats["health"],
        "logs": log_stats,
        "summary": {
            "healthy": all(stats["health"].values()),
            "warnings_24h": log_stats["warning_count"],
            "errors_24h": log_stats["error_count"],
            "critical_failures": log_stats["exit_3_count"]
        }
    }
    
    # Write output
    try:
        with open(output_path, 'w') as f:
            if args.format == 'yaml':
                yaml.dump(report, f, default_flow_style=False)
            else:
                json.dump(report, f, indent=2)
        
        print(f"✅ Pre-loop report generated: {output_path}")
        
        # Print summary
        summary = report["summary"]
        print(f"\n📊 Summary:")
        print(f"   Health: {'✅ OK' if summary['healthy'] else '❌ Issues detected'}")
        print(f"   Warnings (24h): {summary['warnings_24h']}")
        print(f"   Errors (24h): {summary['errors_24h']}")
        print(f"   Critical failures: {summary['critical_failures']}")
        
        if summary["critical_failures"] > 0:
            print(f"\n⚠️  WARNING: {summary['critical_failures']} exit=3 failures detected in recent logs")
            sys.exit(1)
        
        sys.exit(0)
        
    except Exception as e:
        print(f"❌ Failed to write report: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()