#!/usr/bin/env bash
# Generic background runner using nohup. Keeps the process alive after SSH disconnect.
# Usage:
#   bash scripts/run_bg.sh --name JOBNAME [--workdir PATH] -- <your command>
# Example:
#   bash scripts/run_bg.sh --name teacher --workdir . -- python3 train_teacher.py --config configs/nfsde.yaml

set -euo pipefail

NAME=""
WORKDIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --name)
      NAME="$2"; shift 2;;
    --workdir)
      WORKDIR="$2"; shift 2;;
    --)
      shift; break;;
    *)
      echo "Unknown argument: $1"; exit 1;;
  esac
done

CMD="$*"
if [[ -z "$CMD" ]]; then
  echo "No command provided. Use: -- <your command>"; exit 1
fi

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
mkdir -p "$ROOT_DIR/logs" "$ROOT_DIR/pids"

TS="$(date +%Y%m%d-%H%M%S)"
if [[ -z "$NAME" ]]; then NAME="job"; fi
LOG_FILE="$ROOT_DIR/logs/${NAME}_${TS}.log"
PID_FILE="$ROOT_DIR/pids/${NAME}.pid"

# Switch to workdir (default to repo root)
if [[ -n "$WORKDIR" ]]; then
  cd "$WORKDIR"
else
  cd "$ROOT_DIR"
fi

# Run in background and record PID
nohup bash -lc "$CMD" > "$LOG_FILE" 2>&1 & echo $! > "$PID_FILE"

PID="$(cat "$PID_FILE")"
echo "Started '$NAME' (pid $PID)"
echo "Log: $LOG_FILE"
echo "Follow logs: tail -f \"$LOG_FILE\""
echo "Stop: kill \$(cat \"$PID_FILE\")"
