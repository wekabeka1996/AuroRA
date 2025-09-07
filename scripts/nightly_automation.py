#!/usr/bin/env python3
"""
Aurora Nightly Automation Script

Runs comprehensive nightly validation including:
- Mutation testing with baseline comparison
- Coverage analysis with trend tracking
- Golden backtest comparison
- XAI audit trail validation
- Performance regression detection

Usage:
    python scripts/nightly_automation.py [--dry-run] [--verbose]

Environment Variables:
    NIGHTLY_BASELINE_DIR: Directory for baseline files (default: artifacts/baselines)
    NIGHTLY_REPORTS_DIR: Directory for reports (default: artifacts/nightly)
    MUTATION_TIMEOUT: Timeout for mutation testing in seconds (default: 1800)
    COVERAGE_THRESHOLD: Minimum coverage percentage (default: 90)
"""

import os
import sys
import json
import time
import subprocess
import argparse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from common.config import load_config

# Configuration
DEFAULT_BASELINE_DIR = PROJECT_ROOT / "artifacts" / "baselines"
DEFAULT_REPORTS_DIR = PROJECT_ROOT / "artifacts" / "nightly"
MUTATION_TIMEOUT = int(os.getenv("MUTATION_TIMEOUT", "1800"))  # 30 minutes
COVERAGE_THRESHOLD = float(os.getenv("COVERAGE_THRESHOLD", "90"))

class NightlyAutomation:
    """Main class for nightly automation tasks."""

    def __init__(self, baseline_dir: Path = None, reports_dir: Path = None, dry_run: bool = False):
        self.baseline_dir = baseline_dir or DEFAULT_BASELINE_DIR
        self.reports_dir = reports_dir or DEFAULT_REPORTS_DIR
        self.dry_run = dry_run
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Setup directories
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        self.setup_logging()

    def setup_logging(self):
        """Setup logging configuration."""
        log_file = self.reports_dir / f"nightly_{self.timestamp}.log"
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s - %(message)s',
            handlers=[
                logging.FileHandler(log_file),
                logging.StreamHandler(sys.stdout)
            ]
        )
        self.logger = logging.getLogger(__name__)

    def run_command(self, cmd: List[str], cwd: Path = None, timeout: int = None) -> subprocess.CompletedProcess:
        """Run a command with proper error handling."""
        self.logger.info(f"Running command: {' '.join(cmd)}")
        if self.dry_run:
            self.logger.info("[DRY RUN] Would execute command")
            return subprocess.CompletedProcess(cmd, 0, "", "")

        try:
            result = subprocess.run(
                cmd,
                cwd=cwd or PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout
            )
            if result.returncode != 0:
                self.logger.error(f"Command failed: {result.stderr}")
            return result
        except subprocess.TimeoutExpired:
            self.logger.error(f"Command timed out after {timeout} seconds")
            raise

    def mutation_testing(self) -> Dict[str, Any]:
        """Run mutation testing and compare with baseline."""
        self.logger.info("Starting mutation testing...")

        # Check if baseline exists
        baseline_file = self.baseline_dir / "mutation_baseline.json"
        baseline_score = None

        if baseline_file.exists():
            with open(baseline_file) as f:
                baseline_data = json.load(f)
                baseline_score = baseline_data.get("mutation_score")
            self.logger.info(f"Loaded baseline mutation score: {baseline_score}")

        # Run mutation testing
        cmd = [
            "python", "-m", "pytest",
            "--mutants", "src/oms", "src/positions", "src/risk",
            "--output", str(self.reports_dir / f"mutation_{self.timestamp}.json"),
            "--html", str(self.reports_dir / f"mutation_{self.timestamp}.html")
        ]

        try:
            result = self.run_command(cmd, timeout=MUTATION_TIMEOUT)

            if result.returncode == 0:
                # Parse results
                results_file = self.reports_dir / f"mutation_{self.timestamp}.json"
                if results_file.exists():
                    with open(results_file) as f:
                        mutation_data = json.load(f)

                    current_score = mutation_data.get("mutation_score", 0)
                    self.logger.info(f"Current mutation score: {current_score}")

                    # Compare with baseline
                    score_drop = 0
                    if baseline_score is not None:
                        score_drop = baseline_score - current_score
                        self.logger.info(f"Mutation score drop: {score_drop}")

                    # Update baseline if current score is better
                    if baseline_score is None or current_score > baseline_score:
                        self.logger.info("Updating mutation baseline")
                        with open(baseline_file, 'w') as f:
                            json.dump(mutation_data, f, indent=2)

                    return {
                        "status": "success",
                        "current_score": current_score,
                        "baseline_score": baseline_score,
                        "score_drop": score_drop,
                        "threshold_breached": score_drop > 0.05  # 5% drop threshold
                    }
                else:
                    return {"status": "error", "message": "Mutation results file not found"}
            else:
                return {"status": "error", "message": result.stderr}

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "message": f"Mutation testing timed out after {MUTATION_TIMEOUT}s"}

    def coverage_analysis(self) -> Dict[str, Any]:
        """Run coverage analysis and track trends."""
        self.logger.info("Starting coverage analysis...")

        # Run coverage
        cmd = [
            "python", "-m", "pytest",
            "--cov=src",
            "--cov-report=json:coverage.json",
            "--cov-report=html:htmlcov",
            "--cov-report=xml:coverage.xml",
            "--cov-fail-under=0"  # Don't fail, just report
        ]

        result = self.run_command(cmd)

        if result.returncode == 0:
            # Parse coverage results
            coverage_file = PROJECT_ROOT / "coverage.json"
            if coverage_file.exists():
                with open(coverage_file) as f:
                    coverage_data = json.load(f)

                total_coverage = coverage_data.get("totals", {}).get("percent_covered", 0)
                self.logger.info(f"Total coverage: {total_coverage}%")

                # Move coverage files to reports directory
                coverage_files = ["coverage.json", "coverage.xml"]
                htmlcov_dir = PROJECT_ROOT / "htmlcov"

                for file in coverage_files:
                    src = PROJECT_ROOT / file
                    dst = self.reports_dir / f"{file.replace('.json', '')}_{self.timestamp}.json"
                    if src.exists():
                        os.rename(src, dst)

                if htmlcov_dir.exists():
                    import shutil
                    shutil.move(str(htmlcov_dir), str(self.reports_dir / f"htmlcov_{self.timestamp}"))

                # Check coverage threshold
                threshold_breached = total_coverage < COVERAGE_THRESHOLD

                return {
                    "status": "success",
                    "total_coverage": total_coverage,
                    "threshold": COVERAGE_THRESHOLD,
                    "threshold_breached": threshold_breached
                }
            else:
                return {"status": "error", "message": "Coverage results file not found"}
        else:
            return {"status": "error", "message": result.stderr}

    def golden_backtest_comparison(self) -> Dict[str, Any]:
        """Run golden backtest and compare with baseline."""
        self.logger.info("Starting golden backtest comparison...")

        # Check if golden baseline exists
        baseline_file = self.baseline_dir / "golden_backtest_baseline.json"

        # Run backtest
        cmd = [
            "python", "research/golden_backtest.py",
            "--output", str(self.reports_dir / f"golden_backtest_{self.timestamp}.json"),
            "--config", "configs/aurora/production.yaml"
        ]

        result = self.run_command(cmd, timeout=3600)  # 1 hour timeout

        if result.returncode == 0:
            results_file = self.reports_dir / f"golden_backtest_{self.timestamp}.json"

            if results_file.exists():
                with open(results_file) as f:
                    backtest_data = json.load(f)

                # Extract key metrics
                sharpe_ratio = backtest_data.get("sharpe_ratio", 0)
                max_drawdown = backtest_data.get("max_drawdown", 0)
                total_return = backtest_data.get("total_return", 0)

                self.logger.info(f"Backtest results - Sharpe: {sharpe_ratio}, MaxDD: {max_drawdown}, Return: {total_return}")

                # Compare with baseline
                comparison = {}
                if baseline_file.exists():
                    with open(baseline_file) as f:
                        baseline_data = json.load(f)

                    baseline_sharpe = baseline_data.get("sharpe_ratio", 0)
                    baseline_maxdd = baseline_data.get("max_drawdown", 0)

                    sharpe_change = abs(sharpe_ratio - baseline_sharpe)
                    maxdd_change = abs(max_drawdown - baseline_maxdd)

                    comparison = {
                        "sharpe_change": sharpe_change,
                        "maxdd_change": maxdd_change,
                        "sharpe_threshold_breached": sharpe_change > 0.05,  # 0.05 Sharpe change
                        "maxdd_threshold_breached": maxdd_change > 0.05    # 5% MaxDD change
                    }

                    self.logger.info(f"Comparison - Sharpe Δ: {sharpe_change}, MaxDD Δ: {maxdd_change}")

                # Update baseline if this is better
                if not baseline_file.exists() or sharpe_ratio > baseline_data.get("sharpe_ratio", 0):
                    self.logger.info("Updating golden backtest baseline")
                    with open(baseline_file, 'w') as f:
                        json.dump(backtest_data, f, indent=2)

                return {
                    "status": "success",
                    "metrics": {
                        "sharpe_ratio": sharpe_ratio,
                        "max_drawdown": max_drawdown,
                        "total_return": total_return
                    },
                    "comparison": comparison
                }
            else:
                return {"status": "error", "message": "Backtest results file not found"}
        else:
            return {"status": "error", "message": result.stderr}

    def xai_audit_validation(self) -> Dict[str, Any]:
        """Validate XAI audit trail integrity."""
        self.logger.info("Starting XAI audit trail validation...")

        cmd = [
            "python", "-c",
            """
import sys
sys.path.insert(0, '.')
from tests.fixtures.xai_validator import XAIValidator

validator = XAIValidator()
results = validator.validate_recent_events()

print(json.dumps(results))
            """
        ]

        result = self.run_command(cmd)

        if result.returncode == 0:
            try:
                validation_results = json.loads(result.stdout)

                coverage = validation_results.get("coverage", 0)
                missing_ratio = validation_results.get("missing_ratio", 0)
                total_events = validation_results.get("total_events", 0)

                self.logger.info(f"XAI validation - Coverage: {coverage}, Missing: {missing_ratio}, Total: {total_events}")

                return {
                    "status": "success",
                    "coverage": coverage,
                    "missing_ratio": missing_ratio,
                    "total_events": total_events,
                    "threshold_breached": missing_ratio > 0.01  # 1% missing threshold
                }
            except json.JSONDecodeError:
                return {"status": "error", "message": "Invalid validation output"}
        else:
            return {"status": "error", "message": result.stderr}

    def performance_regression_check(self) -> Dict[str, Any]:
        """Check for performance regressions."""
        self.logger.info("Starting performance regression check...")

        # Run performance benchmarks
        cmd = [
            "python", "-m", "pytest",
            "tests/performance/",
            "--benchmark-only",
            "--benchmark-json", str(self.reports_dir / f"performance_{self.timestamp}.json")
        ]

        result = self.run_command(cmd, timeout=1800)  # 30 minutes

        if result.returncode == 0:
            perf_file = self.reports_dir / f"performance_{self.timestamp}.json"

            if perf_file.exists():
                with open(perf_file) as f:
                    perf_data = json.load(f)

                # Extract key metrics
                benchmarks = perf_data.get("benchmarks", [])

                # Check for regressions (simplified - in real implementation would compare with baseline)
                regressions = []
                for benchmark in benchmarks:
                    name = benchmark["name"]
                    mean_time = benchmark["stats"]["mean"]

                    # Define performance thresholds
                    thresholds = {
                        "test_order_submit_latency": 0.5,
                        "test_fill_processing": 0.1,
                        "test_position_update": 0.05
                    }

                    if name in thresholds and mean_time > thresholds[name]:
                        regressions.append({
                            "name": name,
                            "mean_time": mean_time,
                            "threshold": thresholds[name]
                        })

                return {
                    "status": "success",
                    "regressions": regressions,
                    "total_benchmarks": len(benchmarks)
                }
            else:
                return {"status": "error", "message": "Performance results file not found"}
        else:
            return {"status": "error", "message": result.stderr}

    def generate_report(self, results: Dict[str, Any]) -> None:
        """Generate comprehensive nightly report."""
        self.logger.info("Generating nightly report...")

        report = {
            "timestamp": self.timestamp,
            "execution_time": time.time(),
            "results": results,
            "summary": {
                "total_checks": len(results),
                "successful_checks": sum(1 for r in results.values() if r.get("status") == "success"),
                "failed_checks": sum(1 for r in results.values() if r.get("status") != "success"),
                "threshold_breaches": sum(1 for r in results.values() if r.get("threshold_breached", False))
            }
        }

        # Write JSON report
        report_file = self.reports_dir / f"nightly_report_{self.timestamp}.json"
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)

        # Write markdown summary
        md_report = self.reports_dir / f"nightly_report_{self.timestamp}.md"
        with open(md_report, 'w') as f:
            f.write(f"# Aurora Nightly Report\n\n")
            f.write(f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")

            f.write("## Summary\n\n")
            f.write(f"- Total Checks: {report['summary']['total_checks']}\n")
            f.write(f"- Successful: {report['summary']['successful_checks']}\n")
            f.write(f"- Failed: {report['summary']['failed_checks']}\n")
            f.write(f"- Threshold Breaches: {report['summary']['threshold_breaches']}\n\n")

            f.write("## Detailed Results\n\n")

            for check_name, check_result in results.items():
                status = check_result.get("status", "unknown")
                status_emoji = "✅" if status == "success" else "❌" if status == "error" else "⚠️"

                f.write(f"### {status_emoji} {check_name.replace('_', ' ').title()}\n\n")
                f.write(f"**Status:** {status}\n\n")

                if status == "success":
                    # Add relevant metrics
                    if "current_score" in check_result:
                        f.write(f"**Mutation Score:** {check_result['current_score']:.1f}%\n")
                    if "total_coverage" in check_result:
                        f.write(f"**Coverage:** {check_result['total_coverage']:.1f}%\n")
                    if "coverage" in check_result:
                        f.write(f"**XAI Coverage:** {check_result['coverage']:.1f}%\n")
                    if "metrics" in check_result:
                        metrics = check_result["metrics"]
                        f.write("**Backtest Metrics:**\n")
                        for key, value in metrics.items():
                            f.write(f"  - {key}: {value}\n")

                if check_result.get("threshold_breached"):
                    f.write("**⚠️ Threshold Breached**\n")

                if "message" in check_result:
                    f.write(f"**Message:** {check_result['message']}\n")

                f.write("\n")

        self.logger.info(f"Nightly report generated: {md_report}")

    def run_all_checks(self) -> Dict[str, Any]:
        """Run all nightly checks."""
        self.logger.info("Starting nightly automation...")

        results = {}

        # Mutation testing
        results["mutation_testing"] = self.mutation_testing()

        # Coverage analysis
        results["coverage_analysis"] = self.coverage_analysis()

        # Golden backtest comparison
        results["golden_backtest"] = self.golden_backtest_comparison()

        # XAI audit validation
        results["xai_audit"] = self.xai_audit_validation()

        # Performance regression check
        results["performance_check"] = self.performance_regression_check()

        # Generate comprehensive report
        self.generate_report(results)

        # Summary
        successful = sum(1 for r in results.values() if r.get("status") == "success")
        threshold_breaches = sum(1 for r in results.values() if r.get("threshold_breached", False))

        self.logger.info(f"Nightly automation completed: {successful}/{len(results)} successful, {threshold_breaches} threshold breaches")

        return results


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Aurora Nightly Automation")
    parser.add_argument("--dry-run", action="store_true", help="Run in dry-run mode")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument("--baseline-dir", type=Path, help="Baseline directory")
    parser.add_argument("--reports-dir", type=Path, help="Reports directory")

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    automation = NightlyAutomation(
        baseline_dir=args.baseline_dir,
        reports_dir=args.reports_dir,
        dry_run=args.dry_run
    )

    try:
        results = automation.run_all_checks()

        # Exit with error if any critical checks failed
        critical_failures = sum(1 for r in results.values()
                               if r.get("status") != "success" or r.get("threshold_breached", False))

        if critical_failures > 0:
            sys.exit(1)

    except Exception as e:
        automation.logger.error(f"Nightly automation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()