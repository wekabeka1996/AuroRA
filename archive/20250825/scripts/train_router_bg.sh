#!/usr/bin/env bash
# Launch Router training in background
set -euo pipefail
bash "$(dirname "$0")/run_bg.sh" --name router --workdir "$(cd "$(dirname "$0")/.." && pwd)" -- \
  python3 scripts/train_router_from_parquet.py --train data/processed/train.parquet --val data/processed/val.parquet --epochs 10 --checkpoint checkpoints/router_best.pt
