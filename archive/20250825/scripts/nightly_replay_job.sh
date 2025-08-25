#!/usr/bin/env bash
set -euo pipefail

# Nightly replay CI gate script (AUR-CI-701)
# Assumes a replay step produced run_r0_summary.json (or accepts SUMMARY_PATH env)

SUMMARY_PATH=${SUMMARY_PATH:-run_r0_summary.json}
THRESHOLDS_PATH=${THRESHOLDS_PATH:-configs/ci_thresholds.yaml}
PYTHON=${PYTHON:-python}

if [ ! -f "$SUMMARY_PATH" ]; then
  echo "[nightly] summary file missing: $SUMMARY_PATH" >&2
  exit 2
fi
if [ ! -f "$THRESHOLDS_PATH" ]; then
  echo "[nightly] thresholds file missing: $THRESHOLDS_PATH" >&2
  exit 2
fi

echo "[nightly] Applying CI gate: summary=$SUMMARY_PATH thresholds=$THRESHOLDS_PATH"
$PYTHON -m living_latent.core.replay.summarize --summary "$SUMMARY_PATH" --thresholds "$THRESHOLDS_PATH"
rc=$?
if [ $rc -ne 0 ]; then
  echo "[nightly] CI gate FAILED (exit=$rc)" >&2
else
  echo "[nightly] CI gate PASSED" >&2
fi
exit $rc
