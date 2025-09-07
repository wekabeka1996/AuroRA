#!/usr/bin/env python3
"""
Aurora Coverage Snapshot Generator
Generates TEST_COVERAGE_SNAPSHOT.md with module-level coverage analysis
"""

import xml.etree.ElementTree as ET
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Tuple

class CoverageAnalyzer:
    def __init__(self, coverage_xml_path: Path):
        self.coverage_xml_path = coverage_xml_path
        self.tree = ET.parse(coverage_xml_path)
        self.root = self.tree.getroot()

    def parse_coverage(self) -> Dict:
        """Parse coverage XML and extract module-level statistics"""
        modules = {}

        for package in self.root.findall('.//package'):
            package_name = package.get('name', '')

            for class_elem in package.findall('.//class'):
                filename = class_elem.get('filename', '')
                if not filename:
                    continue

                # Extract module name from filename
                if '/' in filename:
                    module_parts = filename.split('/')
                    if len(module_parts) > 1:
                        module_name = module_parts[0]
                    else:
                        module_name = 'root'
                else:
                    module_name = 'root'

                line_rate = float(class_elem.get('line-rate', 0))
                branch_rate = float(class_elem.get('branch-rate', 0))

                if module_name not in modules:
                    modules[module_name] = {
                        'files': [],
                        'total_lines': 0,
                        'covered_lines': 0,
                        'total_branches': 0,
                        'covered_branches': 0
                    }

                # Count lines and branches
                lines_covered = 0
                lines_total = 0
                branches_covered = 0
                branches_total = 0

                for line in class_elem.findall('.//line'):
                    hits = int(line.get('hits', 0))
                    lines_total += 1
                    if hits > 0:
                        lines_covered += 1

                    if line.get('branch') == 'true':
                        branches_total += 1
                        condition_coverage = line.get('condition-coverage', '0%')
                        if '%' in condition_coverage:
                            coverage_pct = float(condition_coverage.split('%')[0])
                            if coverage_pct > 0:
                                branches_covered += 1

                modules[module_name]['files'].append({
                    'filename': filename,
                    'line_rate': line_rate,
                    'branch_rate': branch_rate,
                    'lines_covered': lines_covered,
                    'lines_total': lines_total,
                    'branches_covered': branches_covered,
                    'branches_total': branches_total
                })

                modules[module_name]['total_lines'] += lines_total
                modules[module_name]['covered_lines'] += lines_covered
                modules[module_name]['total_branches'] += branches_total
                modules[module_name]['covered_branches'] += branches_covered

        return modules

    def calculate_module_stats(self, modules: Dict) -> List[Tuple[str, Dict]]:
        """Calculate aggregate statistics for each module"""
        module_stats = []

        for module_name, data in modules.items():
            total_lines = data['total_lines']
            covered_lines = data['covered_lines']
            total_branches = data['total_branches']
            covered_branches = data['covered_branches']

            line_rate = covered_lines / total_lines if total_lines > 0 else 0
            branch_rate = covered_branches / total_branches if total_branches > 0 else 0

            module_stats.append((module_name, {
                'line_rate': line_rate,
                'branch_rate': branch_rate,
                'lines_covered': covered_lines,
                'lines_total': total_lines,
                'branches_covered': covered_branches,
                'branches_total': total_branches,
                'file_count': len(data['files'])
            }))

        # Sort by line coverage (ascending - worst first)
        module_stats.sort(key=lambda x: x[1]['line_rate'])

        return module_stats

    def generate_report(self, output_path: Path) -> str:
        """Generate comprehensive coverage report"""
        modules = self.parse_coverage()
        module_stats = self.calculate_module_stats(modules)

        # Overall statistics from root element
        overall_lines = int(self.root.get('lines-covered', 0))
        overall_lines_total = int(self.root.get('lines-valid', 0))
        overall_branches = int(self.root.get('branches-covered', 0))
        overall_branches_total = int(self.root.get('branches-valid', 0))

        overall_line_rate = overall_lines / overall_lines_total if overall_lines_total > 0 else 0
        overall_branch_rate = overall_branches / overall_branches_total if overall_branches_total > 0 else 0

        report = f"""# Aurora Test Coverage Snapshot

**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

## Executive Summary

| Metric | Value |
|--------|-------|
| **Overall Line Coverage** | {overall_line_rate:.1%} |
| **Overall Branch Coverage** | {overall_branch_rate:.1%} |
| **Lines Covered** | {overall_lines:,}/{overall_lines_total:,} |
| **Branches Covered** | {overall_branches:,}/{overall_branches_total:,} |
| **Modules Analyzed** | {len(module_stats)} |

## Coverage Status

"""

        # Coverage status indicators
        if overall_line_rate >= 0.9:
            report += "🟢 **EXCELLENT** - Line coverage meets or exceeds 90%\n\n"
        elif overall_line_rate >= 0.8:
            report += "🟡 **GOOD** - Line coverage is 80-89%\n\n"
        elif overall_line_rate >= 0.7:
            report += "🟠 **FAIR** - Line coverage is 70-79%\n\n"
        else:
            report += "🔴 **POOR** - Line coverage is below 70%\n\n"

        if overall_branch_rate >= 0.85:
            report += "🟢 **EXCELLENT** - Branch coverage meets or exceeds 85%\n\n"
        elif overall_branch_rate >= 0.7:
            report += "🟡 **GOOD** - Branch coverage is 70-84%\n\n"
        elif overall_branch_rate >= 0.5:
            report += "🟠 **FAIR** - Branch coverage is 50-69%\n\n"
        else:
            report += "🔴 **POOR** - Branch coverage is below 50%\n\n"

        report += """## Module-Level Coverage Analysis

| Module | Line Coverage | Branch Coverage | Files | Lines | Branches |
|--------|---------------|-----------------|-------|-------|----------|
"""

        for module_name, stats in module_stats:
            line_pct = f"{stats['line_rate']:.1%}"
            branch_pct = f"{stats['branch_rate']:.1%}" if stats['branch_rate'] > 0 else "N/A"
            files = stats['file_count']
            lines = f"{stats['lines_covered']}/{stats['lines_total']}"
            branches = f"{stats['branches_covered']}/{stats['branches_total']}" if stats['branches_total'] > 0 else "N/A"

            report += f"| {module_name} | {line_pct} | {branch_pct} | {files} | {lines} | {branches} |\n"

        report += "\n## Critical Modules (< 70% Line Coverage)\n\n"

        critical_modules = [(name, stats) for name, stats in module_stats if stats['line_rate'] < 0.7]

        if critical_modules:
            for module_name, stats in critical_modules:
                report += f"### {module_name}\n"
                report += f"- **Line Coverage:** {stats['line_rate']:.1%}\n"
                report += f"- **Lines:** {stats['lines_covered']}/{stats['lines_total']}\n"
                report += f"- **Files:** {stats['file_count']}\n\n"

                # Show worst files in this module
                module_files = modules[module_name]['files']
                worst_files = sorted(module_files, key=lambda x: x['line_rate'])[:3]

                if worst_files:
                    report += "**Worst Files:**\n"
                    for file_info in worst_files:
                        if file_info['line_rate'] < 0.7:
                            report += f"- `{file_info['filename']}`: {file_info['line_rate']:.1%}\n"
                    report += "\n"
        else:
            report += "✅ No modules with critical coverage gaps found.\n\n"

        report += """## Recommendations

### Immediate Actions
"""

        if overall_line_rate < 0.8:
            report += "1. **Increase line coverage to 80%+**\n"
            report += "   - Focus on modules with <70% coverage\n"
            report += "   - Add unit tests for uncovered functions\n"
            report += "   - Test error handling paths\n\n"

        if overall_branch_rate < 0.7:
            report += "2. **Improve branch coverage to 70%+**\n"
            report += "   - Test conditional logic thoroughly\n"
            report += "   - Cover both true/false branches\n"
            report += "   - Test edge cases and boundary conditions\n\n"

        report += """### Best Practices
1. **Maintain coverage standards** - No PR should reduce coverage
2. **Test-driven development** - Write tests before implementing features
3. **Regular coverage audits** - Review coverage weekly
4. **Focus on critical paths** - Ensure high coverage for business logic

## Mutation Testing Status

*Pending - Run mutation tests on critical modules*

## Files Generated

- `artifacts/coverage.xml` - Detailed XML coverage report
- `artifacts/coverage.json` - JSON format coverage data
- `TEST_COVERAGE_SNAPSHOT.md` - This summary report

---
*Generated by Aurora Coverage Analyzer*
"""

        # Write report
        with open(output_path, 'w', encoding='utf-8') as f:
            f.write(report)

        return str(output_path)

def main():
    """Main entry point"""
    coverage_xml = Path("artifacts/coverage.xml")
    output_file = Path("TEST_COVERAGE_SNAPSHOT.md")

    if not coverage_xml.exists():
        print(f"❌ Coverage XML not found: {coverage_xml}")
        return 1

    analyzer = CoverageAnalyzer(coverage_xml)
    report_path = analyzer.generate_report(output_file)

    print(f"✅ Coverage snapshot generated: {report_path}")
    return 0

if __name__ == "__main__":
    exit(main())