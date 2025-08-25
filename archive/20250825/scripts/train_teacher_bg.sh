#!/usr/bin/env bash
# Launch Teacher training in background
set -euo pipefail
bash "$(dirname "$0")/run_bg.sh" --name teacher --workdir "$(cd "$(dirname "$0")/.." && pwd)" -- \
  python3 train_teacher.py --config configs/nfsde.yaml
