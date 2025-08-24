#!/usr/bin/env python3
"""
Pre-loop Statistics Reporter
Збирає метрики з runs для Go/No-Go критеріїв RC → GA
"""
import json
import os
import glob
import argparse
from pathlib import Path
from typing import Dict, List, Any
from collections import defaultdict
import statistics

def load_run_summary(run_path: Path) -> Dict[str, Any]:
    """Завантажити summary з run директорії"""
    summary_files = list(run_path.glob("summary_*.json"))
    if not summary_files:
        return {}
    
    # Беремо останній summary
    latest_summary = max(summary_files, key=lambda x: x.stat().st_mtime)
    
    try:
        with open(latest_summary, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load {latest_summary}: {e}")
        return {}

def calculate_preloop_stats(summaries: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Розрахувати агреговані статистики preloop"""
    if not summaries:
        return {"error": "No valid summaries found"}
    
    stats = {
        "total_runs": len(summaries),
        "main_loop_started_count": 0,
        "total_decisions": 0,
        "preloop_exits": defaultdict(int),
        "noop_ratios": [],
        "skip_reasons": defaultdict(int),
        "execution_decisions": defaultdict(int)
    }
    
    for summary in summaries:
        # Main loop status
        r2_main = summary.get("r2_main_loop", {})
        if r2_main.get("decisions", 0) > 0:
            stats["main_loop_started_count"] += 1
            stats["total_decisions"] += r2_main["decisions"]
        
        # Preloop exits
        preloop = summary.get("r2_preloop", {})
        exit_kind = preloop.get("exit_kind", "unknown")
        stats["preloop_exits"][exit_kind] += 1
        
        # NOOP ratio
        if r2_main.get("decisions", 0) > 0:
            noop_count = r2_main.get("noop_decisions", 0)
            noop_ratio = noop_count / r2_main["decisions"]
            stats["noop_ratios"].append(noop_ratio)
        
        # Skip reasons
        skip_reasons = preloop.get("skip_reasons", {})
        for reason, count in skip_reasons.items():
            stats["skip_reasons"][reason] += count
        
        # Execution decisions
        exec_decisions = r2_main.get("execution_decisions", {})
        for decision, count in exec_decisions.items():
            stats["execution_decisions"][decision] += count
    
    # Calculate derived metrics
    stats["main_loop_started_ratio"] = stats["main_loop_started_count"] / stats["total_runs"]
    stats["preloop_exit_ratio"] = stats["preloop_exits"]["exit"] / stats["total_runs"]
    
    if stats["noop_ratios"]:
        stats["noop_ratio_mean"] = statistics.mean(stats["noop_ratios"])
        stats["noop_ratio_median"] = statistics.median(stats["noop_ratios"])
        stats["noop_ratio_max"] = max(stats["noop_ratios"])
    else:
        stats["noop_ratio_mean"] = 1.0
        stats["noop_ratio_median"] = 1.0 
        stats["noop_ratio_max"] = 1.0
    
    return stats

def evaluate_ga_gates(stats: Dict[str, Any]) -> Dict[str, Any]:
    """Оцінити Go/No-Go критерії для GA"""
    individual_gates = {
        "main_loop_started_ratio": {
            "value": stats.get("main_loop_started_ratio", 0),
            "threshold": 0.95,
            "passed": stats.get("main_loop_started_ratio", 0) >= 0.95
        },
        "decisions_per_run": {
            "value": stats.get("total_decisions", 0) / max(stats.get("total_runs", 1), 1),
            "threshold": 1.0,
            "passed": stats.get("total_decisions", 0) >= stats.get("total_runs", 0)
        },
        "preloop_exit_ratio": {
            "value": stats.get("preloop_exit_ratio", 0),
            "threshold": 0.7,
            "passed": stats.get("preloop_exit_ratio", 0) >= 0.7
        },
        "noop_ratio_mean": {
            "value": stats.get("noop_ratio_mean", 1.0),
            "threshold": 0.85,
            "passed": stats.get("noop_ratio_mean", 1.0) <= 0.85
        },
        "zero_budget_count": {
            "value": stats.get("skip_reasons", {}).get("zero_budget", 0),
            "threshold": 0,
            "passed": stats.get("skip_reasons", {}).get("zero_budget", 0) == 0
        }
    }
    
    # Calculate overall gate status
    all_gates_passed = all(gate["passed"] for gate in individual_gates.values())
    
    return {
        "gates": individual_gates,
        "overall_passed": all_gates_passed
    }

def generate_prometheus_metrics(stats: Dict[str, Any], gates_result: Dict[str, Any]) -> str:
    """Генерувати Prometheus метрики"""
    metrics = []
    gates = gates_result["gates"]
    
    # Basic stats
    metrics.append(f"lla_preloop_report_runs_total {stats['total_runs']}")
    metrics.append(f"lla_preloop_report_main_loop_started_ratio {stats['main_loop_started_ratio']:.3f}")
    metrics.append(f"lla_preloop_report_noop_ratio_mean {stats['noop_ratio_mean']:.3f}")
    metrics.append(f"lla_preloop_report_preloop_exit_ratio {stats['preloop_exit_ratio']:.3f}")
    
    # Gate results
    for gate_name, gate_info in gates.items():
        passed_value = 1 if gate_info["passed"] else 0
        metrics.append(f"lla_preloop_gate_passed{{gate=\"{gate_name}\"}} {passed_value}")
        metrics.append(f"lla_preloop_gate_value{{gate=\"{gate_name}\"}} {gate_info['value']:.3f}")
    
    # Overall gate status
    overall_passed = 1 if gates_result["overall_passed"] else 0
    metrics.append(f"lla_preloop_gates_overall_passed {overall_passed}")
    
    # Skip reasons
    for reason, count in stats.get("skip_reasons", {}).items():
        metrics.append(f"lla_preloop_skip_reasons_total{{reason=\"{reason}\"}} {count}")
    
    # Execution decisions
    for decision, count in stats.get("execution_decisions", {}).items():
        metrics.append(f"lla_preloop_execution_decisions_total{{decision=\"{decision}\"}} {count}")
    
    return "\n".join(metrics)

def main():
    parser = argparse.ArgumentParser(description="Generate preloop statistics report")
    parser.add_argument("--root", default="runs", help="Root directory containing run folders")
    parser.add_argument("--glob", default="run_*", help="Glob pattern for run folders")
    parser.add_argument("--out", default="artifacts/preloop_report.json", help="Output JSON file")
    parser.add_argument("--prom", default="artifacts/preloop_metrics.prom", help="Prometheus metrics file")
    parser.add_argument("--artifacts-dir", default="artifacts", help="Artifacts directory")
    
    args = parser.parse_args()
    
    # Ensure artifacts directory exists
    Path(args.artifacts_dir).mkdir(exist_ok=True)
    
    # Find run directories
    run_pattern = os.path.join(args.root, args.glob)
    run_dirs = [Path(p) for p in glob.glob(run_pattern) if os.path.isdir(p)]
    
    print(f"Found {len(run_dirs)} run directories matching {run_pattern}")
    
    if not run_dirs:
        print("No run directories found!")
        return 1
    
    # Load summaries
    summaries = []
    for run_dir in run_dirs:
        summary = load_run_summary(run_dir)
        if summary:
            summaries.append(summary)
    
    print(f"Loaded {len(summaries)} valid summaries")
    
    # Calculate statistics
    stats = calculate_preloop_stats(summaries)
    gates_result = evaluate_ga_gates(stats)
    
    # Generate report
    report = {
        "timestamp": "2025-08-21T12:00:00Z",  # Would use real timestamp
        "stats": stats,
        "gates": gates_result,
        "recommendation": "GO" if gates_result["overall_passed"] else "NO-GO"
    }
    
    # Write JSON report
    with open(args.out, 'w') as f:
        json.dump(report, f, indent=2, default=str)
    
    print(f"✅ Report written to {args.out}")
    
    # Write Prometheus metrics
    prom_metrics = generate_prometheus_metrics(stats, gates_result)
    with open(args.prom, 'w') as f:
        f.write(prom_metrics)
    
    print(f"✅ Prometheus metrics written to {args.prom}")
    
    # Print summary
    print(f"\n📊 Summary:")
    print(f"  Runs analyzed: {stats['total_runs']}")
    print(f"  Main loop started ratio: {stats['main_loop_started_ratio']:.1%}")
    print(f"  Average NOOP ratio: {stats['noop_ratio_mean']:.1%}")
    print(f"  Preloop exit ratio: {stats['preloop_exit_ratio']:.1%}")
    print(f"  Zero budget violations: {stats['skip_reasons'].get('zero_budget', 0)}")
    print(f"\n🚦 GA Gates: {'✅ PASSED' if gates_result['overall_passed'] else '❌ FAILED'}")
    
    for gate_name, gate_info in gates_result["gates"].items():
        status = "✅" if gate_info["passed"] else "❌"
        print(f"  {gate_name}: {status} ({gate_info['value']:.3f} vs {gate_info['threshold']})")
    
    return 0 if gates_result["overall_passed"] else 1

if __name__ == "__main__":
    exit(main())