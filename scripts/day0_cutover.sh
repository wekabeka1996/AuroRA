#!/usr/bin/env bash
# AURORA Day-0 Cutover - Pure CLI Commands for Copilot
# Ready to copy-paste execution

set -e  # Exit on any error

echo "🚀 AURORA Day-0 GA Cutover Starting"
echo "=================================="

# STEP 1: Version and Tag
echo ""
echo "📋 STEP 1: Version and Tag"
echo "0.4.0" > VERSION
echo "✅ VERSION updated to 0.4.0"

# Create git tag (ignore if git not available)
git tag -a v0.4.0 -m "AURORA GA 0.4.0" 2>/dev/null || echo "⚠️ Git tag skipped (git not available)"

# STEP 2: Profile Lock Validation (CRITICAL)
echo ""
echo "🔒 STEP 2: Profile Lock Validation (CRITICAL)"
python scripts/mk_profile_lock.py --in configs/profiles/r2.yaml --validate
if [ $? -ne 0 ]; then
    echo "❌ CRITICAL: r2 profile lock validation failed"
    exit 3
fi
echo "✅ r2 profile lock validated"

python scripts/validate_profiles.py --profile configs/profiles/r2.yaml --lock configs/profiles/r2.lock.json
if [ $? -ne 0 ]; then
    echo "❌ CRITICAL: r2 profile integrity check failed"
    exit 3
fi
echo "✅ r2 profile integrity verified"

# STEP 3: Hard-gating Mode Check
echo ""
echo "⚡ STEP 3: Hard-gating Mode Check"

# Check no panic flag exists
if [ -f "artifacts/ci/hard_panic.flag" ]; then
    echo "❌ CRITICAL: Panic flag exists - remove before cutover"
    echo "File: artifacts/ci/hard_panic.flag"
    exit 3
else
    echo "✅ No panic flag found"
fi

echo "⚠️ MANUAL CHECK: Verify master.yaml has ci_gating.hard_override: auto"

# STEP 4: Monitoring Setup
echo ""
echo "📊 STEP 4: Monitoring Setup"

# Create artifacts directory
mkdir -p artifacts/ga

# Validate monitoring files
if [ -f "monitoring/aurora_alerts.yml" ]; then
    python -c "import yaml; yaml.safe_load(open('monitoring/aurora_alerts.yml'))" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✅ Alerts YAML validated"
    else
        echo "❌ Invalid alerts YAML"
        exit 1
    fi
fi

if [ -f "monitoring/aurora_dashboard.json" ]; then
    python -c "import json; json.load(open('monitoring/aurora_dashboard.json'))" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "✅ Dashboard JSON validated"
    else
        echo "❌ Invalid dashboard JSON"
        exit 1
    fi
fi

echo "⚠️ MANUAL: Import dashboard to Grafana and enable alerts"

# STEP 5: Smoke Test
echo ""
echo "💨 STEP 5: GA Readiness Smoke Test"

# Quick canary test
python scripts/canary_run.py --profile configs/profiles/r2.yaml --runs 3 --gating=soft --output artifacts/ga/cutover_canary.json
if [ $? -ne 0 ]; then
    echo "❌ CRITICAL: Cutover canary tests failed"
    exit 1
fi
echo "✅ Cutover canary tests passed"

# GA Gates evaluation
python scripts/ga_gates_eval.py --format md --output artifacts/ga/cutover_gates.md
if [ $? -ne 0 ]; then
    echo "❌ CRITICAL: GA gates evaluation failed"
    exit 1
fi
echo "✅ GA gates evaluation passed"

echo ""
echo "🎉 DAY-0 CUTOVER COMPLETED SUCCESSFULLY!"
echo "========================================"
echo "📋 Next steps:"
echo "1. Enable hard gating in master.yaml"
echo "2. Import Grafana dashboard"
echo "3. Start 24h watch monitoring"
echo "4. Review artifacts/ga/cutover_* files"
echo ""
echo "🔄 Start 24h monitoring with:"
echo "python scripts/watch_24h.py --continuous --hours 24"