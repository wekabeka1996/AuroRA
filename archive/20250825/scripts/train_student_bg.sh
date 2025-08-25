#!/usr/bin/env bash
# Launch Student training in background
set -euo pipefail
bash "$(dirname "$0")/run_bg.sh" --name student --workdir "$(cd "$(dirname "$0")/.." && pwd)" -- \
  python3 train_student.py --config configs/dssm.yaml --dataset_parquet data/processed/train.parquet
