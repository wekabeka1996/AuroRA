#!/usr/bin/env bash
set -euo pipefail

if [[ -z "${AURORA_OPS_TOKEN:-}" ]]; then echo 'AURORA_OPS_TOKEN not set'; exit 1; fi

snapshot() { curl -sS -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" http://127.0.0.1:8000/risk/snapshot; }
setrisk() { curl -sS -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" -H 'Content-Type: application/json' -d "$1" http://127.0.0.1:8000/risk/set; }

s1=$(snapshot); echo "Snapshot1: $s1" | jq '.' || true
upd='{"dd_day_pct":3,"max_concurrent":5,"size_scale":0.7}'
s2=$(setrisk "$upd"); echo "After set: $s2" | jq '.' || true
s3=$(snapshot); echo "Snapshot2: $s3" | jq '.' || true

ok1=$(echo "$s3" | jq -r '.risk.dd_day_pct == 3 and .risk.max_concurrent == 5 and (.risk.size_scale|tonumber) == 0.7')
if [[ "$ok1" == "true" ]]; then echo 'QA ops risk: PASS'; exit 0; else echo 'QA ops risk: FAIL'; exit 1; fi
