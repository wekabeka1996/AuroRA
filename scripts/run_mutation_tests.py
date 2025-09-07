#!/usr/bin/env python3
"""
Aurora Mutation Testing Script

Runs mutation testing on critical packages and compares with baseline.

Usage:
    python scripts/run_mutation_tests.py [--baseline] [--compare] [--html] [--timeout SECONDS]

Options:
    --baseline    Create/update baseline mutation scores
    --compare     Compare current scores with baseline
    --html        Generate HTML report
    --timeout     Timeout in seconds (default: 1800)
    --packages    Comma-separated list of packages to test (default: oms,positions,risk)
"""

import os
import sys
import json
import time
import argparse
from pathlib import Path
from typing import List, Dict, Any
import logging

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

class MutationTester:
    """Handles mutation testing operations."""

    def __init__(self, baseline_dir: Path = None, reports_dir: Path = None):
        self.baseline_dir = baseline_dir or PROJECT_ROOT / "artifacts" / "baselines"
        self.reports_dir = reports_dir or PROJECT_ROOT / "artifacts" / "reports"
        self.baseline_file = self.baseline_dir / "mutation_baseline.json"

        # Setup directories
        self.baseline_dir.mkdir(parents=True, exist_ok=True)
        self.reports_dir.mkdir(parents=True, exist_ok=True)

        # Setup logging
        logging.basicConfig(level=logging.INFO)
        self.logger = logging.getLogger(__name__)

    def run_mutation_test(self, packages: List[str], timeout: int = 1800,
                         html_report: bool = False) -> Dict[str, Any]:
        """Run mutation testing on specified packages."""

        self.logger.info(f"Running mutation tests on packages: {', '.join(packages)}")

        # Prepare command
        cmd = ["python", "-m", "mutpy"]

        # Add target packages
        for package in packages:
            # Handle both src/ and core/ paths
            if package.startswith('core/'):
                cmd.extend(["--target", package])
            else:
                cmd.extend(["--target", f"src/{package}"])

        # Add test discovery
        cmd.extend(["--unit-test", "tests/"])

        # Add output options
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        json_output = self.reports_dir / f"mutation_results_{timestamp}.json"
        cmd.extend(["--output", str(json_output)])

        if html_report:
            html_output = self.reports_dir / f"mutation_report_{timestamp}.html"
            cmd.extend(["--report-html", str(html_output)])

        # Add mutation operators (common ones)
        cmd.extend([
            "--operator", "AOD",  # Arithmetic Operator Deletion
            "--operator", "AOR",  # Arithmetic Operator Replacement
            "--operator", "COD",  # Conditional Operator Deletion
            "--operator", "COI",  # Conditional Operator Insertion
            "--operator", "CRP",  # Constant Replacement
            "--operator", "ROR",  # Relational Operator Replacement
        ])

        self.logger.info(f"Executing: {' '.join(cmd)}")

        # Run mutation testing
        import subprocess
        try:
            result = subprocess.run(
                cmd,
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                # Parse results
                if json_output.exists():
                    with open(json_output) as f:
                        mutation_data = json.load(f)

                    # Extract summary
                    summary = mutation_data.get("summary", {})
                    killed = summary.get("killed", 0)
                    survived = summary.get("survived", 0)
                    timeout_count = summary.get("timeout", 0)
                    error_count = summary.get("error", 0)

                    total_mutants = killed + survived + timeout_count + error_count
                    mutation_score = (killed / total_mutants * 100) if total_mutants > 0 else 0

                    results = {
                        "status": "success",
                        "mutation_score": mutation_score,
                        "killed": killed,
                        "survived": survived,
                        "timeout": timeout_count,
                        "error": error_count,
                        "total_mutants": total_mutants,
                        "packages_tested": packages,
                        "timestamp": timestamp
                    }

                    self.logger.info(".1f")
                    self.logger.info(f"Results: {killed} killed, {survived} survived, {timeout_count} timeout, {error_count} errors")

                    return results
                else:
                    return {"status": "error", "message": "Results file not found"}
            else:
                return {"status": "error", "message": result.stderr}

        except subprocess.TimeoutExpired:
            return {"status": "timeout", "message": f"Mutation testing timed out after {timeout} seconds"}

    def create_baseline(self, packages: List[str], timeout: int = 1800) -> Dict[str, Any]:
        """Create or update mutation testing baseline."""

        self.logger.info("Creating mutation testing baseline...")

        results = self.run_mutation_test(packages, timeout, html_report=True)

        if results["status"] == "success":
            # Save as baseline
            with open(self.baseline_file, 'w') as f:
                json.dump(results, f, indent=2)

            self.logger.info(f"Baseline saved to {self.baseline_file}")
            return {"status": "success", "baseline_file": str(self.baseline_file)}
        else:
            return results

    def compare_with_baseline(self, packages: List[str], timeout: int = 1800) -> Dict[str, Any]:
        """Compare current mutation scores with baseline."""

        self.logger.info("Comparing with mutation testing baseline...")

        if not self.baseline_file.exists():
            return {"status": "error", "message": "Baseline file not found. Run with --baseline first."}

        # Load baseline
        with open(self.baseline_file) as f:
            baseline = json.load(f)

        baseline_score = baseline.get("mutation_score", 0)
        self.logger.info(f"Baseline score: {baseline_score:.1f}%")
        # Run current test
        current_results = self.run_mutation_test(packages, timeout)

        if current_results["status"] == "success":
            current_score = current_results["mutation_score"]
            score_diff = current_score - baseline_score

            comparison = {
                "status": "success",
                "baseline_score": baseline_score,
                "current_score": current_score,
                "score_difference": score_diff,
                "improvement": score_diff > 0,
                "regression": score_diff < -0.05,  # 5% regression threshold
                "current_results": current_results
            }

            self.logger.info(f"Current score: {current_score:.1f}%, diff: {score_diff:.1f}%")
            if comparison["regression"]:
                self.logger.warning("⚠️  Mutation score regression detected!")

            return comparison
        else:
            return current_results

    def generate_report(self, results: Dict[str, Any], output_file: Path = None) -> str:
        """Generate human-readable mutation testing report."""

        if output_file is None:
            timestamp = time.strftime("%Y%m%d_%H%M%S")
            output_file = self.reports_dir / f"mutation_report_{timestamp}.md"

        report = f"""# Aurora Mutation Testing Report

**Generated:** {time.strftime("%Y-%m-%d %H:%M:%S")}

## Summary

- **Status:** {results.get("status", "unknown").title()}
- **Mutation Score:** {results.get("mutation_score", 0):.1f}%
- **Total Mutants:** {results.get("total_mutants", 0)}
- **Killed:** {results.get("killed", 0)}
- **Survived:** {results.get("survived", 0)}
- **Timeout:** {results.get("timeout", 0)}
- **Errors:** {results.get("error", 0)}

## Package Coverage

"""

        packages = results.get("packages_tested", [])
        if packages:
            report += "Packages tested:\n"
            for package in packages:
                report += f"- `src/{package}`\n"
        else:
            report += "No packages specified\n"

        report += "\n## Detailed Results\n\n"

        if results.get("status") == "success":
            killed = results.get("killed", 0)
            survived = results.get("survived", 0)
            total = results.get("total_mutants", 0)

            if total > 0:
                kill_rate = killed / total * 100
                survival_rate = survived / total * 100

                report += f"""
### Mutation Effectiveness

- **Kill Rate:** {kill_rate:.1f}% ({killed}/{total})
- **Survival Rate:** {survival_rate:.1f}% ({survived}/{total})

### Interpretation

- **High Kill Rate (>80%)**: Excellent test coverage
- **Medium Kill Rate (60-80%)**: Good test coverage
- **Low Kill Rate (<60%)**: Insufficient test coverage

"""

        # Recommendations
        score = results.get("mutation_score", 0)
        if score < 60:
            report += "### Recommendations\n\n"
            report += "🔴 **Critical**: Mutation score is too low. Focus on:\n"
            report += "1. Adding more unit tests for critical paths\n"
            report += "2. Improving test assertions\n"
            report += "3. Testing edge cases and error conditions\n"
            report += "4. Reviewing test coverage gaps\n\n"
        elif score < 80:
            report += "### Recommendations\n\n"
            report += "🟡 **Warning**: Mutation score could be improved:\n"
            report += "1. Add tests for complex business logic\n"
            report += "2. Test error handling paths\n"
            report += "3. Add integration tests\n\n"
        else:
            report += "### Recommendations\n\n"
            report += "🟢 **Excellent**: Mutation score is strong. Maintain by:\n"
            report += "1. Keeping tests up to date with code changes\n"
            report += "2. Adding tests for new features\n"
            report += "3. Regular mutation testing\n\n"

        # Write report
        with open(output_file, 'w') as f:
            f.write(report)

        self.logger.info(f"Report generated: {output_file}")
        return str(output_file)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Aurora Mutation Testing")
    parser.add_argument("--baseline", action="store_true", help="Create/update baseline")
    parser.add_argument("--compare", action="store_true", help="Compare with baseline")
    parser.add_argument("--html", action="store_true", help="Generate HTML report")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    parser.add_argument("--packages", default="oms,positions,risk",
                       help="Comma-separated list of packages to test")
    parser.add_argument("--output", type=Path, help="Output file for report")

    args = parser.parse_args()

    # Parse packages
    packages = [p.strip() for p in args.packages.split(",")]

    # Initialize tester
    tester = MutationTester()

    try:
        if args.baseline:
            results = tester.create_baseline(packages, args.timeout)
        elif args.compare:
            results = tester.compare_with_baseline(packages, args.timeout)
        else:
            results = tester.run_mutation_test(packages, args.timeout, args.html)

        # Generate report
        if results["status"] == "success":
            report_file = tester.generate_report(results, args.output)
            print(f"Report generated: {report_file}")

            # Exit with error if regression detected
            if results.get("regression"):
                print("❌ Mutation score regression detected!")
                sys.exit(1)
        else:
            print(f"❌ Mutation testing failed: {results.get('message', 'Unknown error')}")
            sys.exit(1)

    except Exception as e:
        print(f"❌ Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()