#!/bin/bash
#
# This script runs a full code duplication analysis pipeline.
# 1. Runs jscpd for copy-paste detection.
# 2. Runs pylint for semantic similarity detection.
# 3. Runs radon for cyclomatic complexity analysis.
# 4. Runs the Python analyzer to unify results and generate reports.

set -e
echo "Starting code duplication analysis pipeline..."

# Ensure the script is run from the project root
if [ ! -f "README.md" ]; then
    echo "Error: This script must be run from the project root directory."
    exit 1
fi

# --- Configuration ---
REPORTS_DIR="reports"
JSCPD_DIR="$REPORTS_DIR/jscpd"
PYLINT_REPORT="$REPORTS_DIR/pylint_dupl.txt"
RADON_REPORT="$REPORTS_DIR/radon_cc.txt"
ANALYSIS_SCRIPT="tools/analyze_duplicates.py"

# --- Setup ---
echo "Creating report directories..."
mkdir -p "$JSCPD_DIR"

# --- Tool Execution ---

# 1. Run jscpd
echo "Running jscpd for copy-paste analysis..."
jscpd . --reporters json --output "$JSCPD_DIR" --ignore "**/.venv/**,**/node_modules/**,**/__pycache__/**,**/*.json,**/*.md,**/*.txt" --no-silent --min-tokens 50
echo "jscpd report generated in $JSCPD_DIR"

# 2. Run pylint for semantic duplicates
echo "Running pylint for semantic similarity analysis..."
# Use PYTHONIOENCODING=utf-8 to prevent UnicodeEncodeError on Windows
export PYTHONIOENCODING=utf-8
pylint --disable=all --enable=similarities $(git ls-files '*.py') > "$PYLINT_REPORT" || true
echo "Pylint report generated at $PYLINT_REPORT"

# 3. Run Radon for complexity
echo "Running radon for cyclomatic complexity analysis..."
radon cc . -a -s --exclude ".venv/*,*/__pycache__/*" > "$RADON_REPORT" || true
echo "Radon report generated at $RADON_REPORT"

# --- Analysis ---
echo "Running analysis script to unify results..."
python "$ANALYSIS_SCRIPT"

# --- Completion ---
echo ""
echo "✅ Duplication analysis complete!"
echo "Reports have been generated in the '$REPORTS_DIR' directory:"
echo "  - Full data: duplicate_clusters.json"
echo "  - Audit summary: duplicate_audit.md"
