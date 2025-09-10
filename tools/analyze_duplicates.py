import json
import re
from collections import defaultdict
from pathlib import Path

REPORTS_DIR = Path(__file__).parent.parent / "reports"
JSCPD_REPORT_PATH = REPORTS_DIR / "jscpd" / "jscpd-report.json"
PYLINT_REPORT_PATH = REPORTS_DIR / "pylint_dupl.txt"
RADON_REPORT_PATH = REPORTS_DIR / "radon_cc.txt"

OUTPUT_CLUSTERS_PATH = REPORTS_DIR / "duplicate_clusters.json"
OUTPUT_AUDIT_PATH = REPORTS_DIR / "duplicate_audit.md"


def parse_jscpd_report():
    """Parses the jscpd JSON report to extract duplication data."""
    print(f"Parsing jscpd report: {JSCPD_REPORT_PATH}")
    if not JSCPD_REPORT_PATH.exists():
        print(f"jscpd report not found at {JSCPD_REPORT_PATH}")
        return []

    with open(JSCPD_REPORT_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    duplicates = data.get("duplicates", [])
    print(f"Found {len(duplicates)} duplication instances in jscpd report.")
    return duplicates


def parse_pylint_report():
    """Parses the pylint duplicates text report."""
    print(f"Parsing pylint report: {PYLINT_REPORT_PATH}")
    if not PYLINT_REPORT_PATH.exists():
        print(f"Pylint report not found at {PYLINT_REPORT_PATH}")
        return []

    with open(PYLINT_REPORT_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Regex to find blocks of similar lines
    # A block starts with a line containing "R0801: Similar lines..."
    # and captures everything until the next such line or end of file.
    similar_blocks_regex = re.compile(
        r"R0801: Similar lines in (\d+) files\n(.*?)(?=\n.*R0801: Similar lines|\Z)",
        re.DOTALL,
    )

    clusters = []
    for match in similar_blocks_regex.finditer(content):
        num_files = int(match.group(1))
        block_content = match.group(2)

        # Regex to find file paths and line numbers within a block
        # Handles both windows and posix paths
        file_loc_regex = re.compile(r"==\s*(.*?):\[(\d+):(\d+)\]")

        locations = []
        # The code snippet is at the end of the block content
        code_snippet_raw = file_loc_regex.sub("", block_content).strip()

        for file_match in file_loc_regex.finditer(block_content):
            file_path = file_match.group(1).strip().replace("\\", "/")
            start_line = int(file_match.group(2))
            end_line = int(file_match.group(3))
            locations.append({"file": file_path, "start": start_line, "end": end_line})

        # The number of found locations should match the number in the header
        if locations:
            clusters.append(
                {
                    "locations": locations,
                    "num_files": len(locations),
                    "code_snippet": code_snippet_raw.split("\n", 1)[
                        -1
                    ],  # Remove the first line which might be part of the file list
                }
            )

    print(f"Found {len(clusters)} duplication clusters in pylint report.")
    return clusters


def parse_radon_report():
    """Parses the radon cyclomatic complexity report."""
    print(f"Parsing radon report: {RADON_REPORT_PATH}")
    if not RADON_REPORT_PATH.exists():
        print(f"Radon report not found at {RADON_REPORT_PATH}")
        return {}

    with open(RADON_REPORT_PATH, "r", encoding="utf-8") as f:
        lines = f.readlines()

    complexity_map = {}
    current_file = None
    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Check if the line is a file path
        if not line.startswith(("M", "F", "C")):
            current_file = line
            continue

        # Regex to parse the complexity line
        match = re.match(r"(\w) (\d+):(\d+) (.*) - (\w) \((\d+)\)", line)
        if match and current_file:
            obj_type, start_line, _, name, rank, complexity = match.groups()
            key = f"{current_file}:{name}"
            complexity_map[key] = {"rank": rank, "complexity": int(complexity)}

    print(f"Parsed {len(complexity_map)} objects from radon report.")
    return complexity_map


def main():
    """
    Main function to run the duplicate analysis pipeline.
    """
    jscpd_duplicates = parse_jscpd_report()
    pylint_clusters = parse_pylint_report()
    radon_complexity = parse_radon_report()

    unified_clusters = unify_and_cluster_duplicates(
        jscpd_duplicates, pylint_clusters, radon_complexity
    )

    write_reports(unified_clusters)


def unify_and_cluster_duplicates(jscpd_duplicates, pylint_clusters, radon_complexity):
    """
    Unifies duplicates from different sources and enriches them with complexity data.
    """
    all_clusters = []

    # 1. Process and normalize jscpd data
    for dup in jscpd_duplicates:
        locations = [
            {
                "file": dup["firstFile"]["name"].replace("\\", "/"),
                "start": dup["firstFile"]["start"],
                "end": dup["firstFile"]["end"],
            },
            {
                "file": dup["secondFile"]["name"].replace("\\", "/"),
                "start": dup["secondFile"]["start"],
                "end": dup["secondFile"]["end"],
            },
        ]
        cluster = {
            "source": "jscpd",
            "lines": dup["lines"],
            "tokens": dup["tokens"],
            "code_snippet": dup["fragment"],
            "locations": locations,
        }
        all_clusters.append(cluster)

    # 2. Process and normalize pylint data
    for p_cluster in pylint_clusters:
        cluster = {
            "source": "pylint",
            "lines": len(p_cluster.get("code_snippet", "").split("\n")),
            "tokens": 0,  # Pylint doesn't provide token count
            "code_snippet": p_cluster.get("code_snippet", ""),
            "locations": p_cluster.get("locations", []),
        }
        all_clusters.append(cluster)

    # 3. Enrich with Radon complexity data
    # Create a file-centric map from radon data for easier lookup
    radon_by_file = defaultdict(list)
    for key, value in radon_complexity.items():
        file_path, obj_name = key.rsplit(":", 1)
        radon_by_file[file_path].append({"name": obj_name, **value})

    for cluster in all_clusters:
        for loc in cluster["locations"]:
            file_path = loc["file"]
            if file_path in radon_by_file:
                # Find functions/classes that contain this duplicate block
                relevant_metrics = []
                for metric in radon_by_file[file_path]:
                    # This is a simplification: we don't have end lines from radon.
                    # We assume if a duplicate starts after a function starts, it might be in it.
                    # A more accurate check would require full AST parsing.
                    if "start_line" in metric and metric["start_line"] <= loc["start"]:
                        relevant_metrics.append(metric)

                if relevant_metrics:
                    loc["complexity_metrics"] = relevant_metrics

    print(f"Created a unified list of {len(all_clusters)} duplication clusters.")
    return all_clusters


def write_reports(clusters):
    """Writes the unified clusters to JSON and a summary to Markdown."""

    # Write JSON report
    print(f"Writing unified JSON report to {OUTPUT_CLUSTERS_PATH}")
    with open(OUTPUT_CLUSTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(clusters, f, indent=2)

    # Write Markdown audit report
    print(f"Writing Markdown audit report to {OUTPUT_AUDIT_PATH}")
    with open(OUTPUT_AUDIT_PATH, "w", encoding="utf-8") as f:
        f.write("# Code Duplication Audit Report\n\n")
        f.write(
            f"Found a total of **{len(clusters)}** duplication clusters from `jscpd` and `pylint`.\n\n"
        )

        # Sort clusters by the number of lines duplicated
        clusters.sort(key=lambda x: x.get("lines", 0), reverse=True)

        for i, cluster in enumerate(clusters[:30]):  # Report top 30 largest duplicates
            f.write(
                f"## Cluster {i+1}: {cluster['lines']} lines ({cluster['tokens']} tokens) | Source: {cluster['source']}\n\n"
            )
            f.write("Locations:\n")
            for loc in cluster["locations"]:
                f.write(f"- `{loc['file']}` (Lines: {loc['start']}-{loc['end']})\n")
                if "complexity_metrics" in loc:
                    f.write("  - **Potential Complexity Issues (Radon):**\n")
                    for metric in loc["complexity_metrics"]:
                        if metric["rank"] > "A":  # Only show non-trivial complexity
                            f.write(
                                f"    - `{metric['name']}`: Rank **{metric['rank']}** (Complexity: {metric['complexity']})\n"
                            )

            f.write("\n```python\n")
            f.write(cluster["code_snippet"])
            f.write("\n```\n\n")
            f.write("---\n\n")

    print("Reports generated successfully.")


if __name__ == "__main__":
    main()
