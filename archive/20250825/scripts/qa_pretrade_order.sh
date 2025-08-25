#!/usr/bin/env bash
set -euo pipefail

check() {
  local payload="$1"
  curl -sS -H 'Content-Type: application/json' -d "$payload" http://127.0.0.1:8000/pretrade/check
}

base='{"account":{"mode":"shadow"},"order":{"symbol":"BTCUSDT","side":"buy","qty":1.0,"base_notional":100.0},"market":{"latency_ms":5,"slip_bps_est":0.5,"a_bps":10.0,"b_bps":20.0,"score":0.5,"mode_regime":"normal","spread_bps":5.0,"trap_cancel_deltas":[0,0],"trap_add_deltas":[0,0],"trap_trades_cnt":10},"fees_bps":0.1}'

# 1) TRAP deny
export TRAP_GUARD=on
p1=$(echo "$base" | jq '.market.trap_cancel_deltas=[100,100] | .market.trap_add_deltas=[0.1,0.1]')
r1=$(check "$p1")
echo "TRAP deny: $r1" | jq '.' || true

# 2) ER deny
unset TRAP_GUARD || true
p2=$(echo "$base" | jq '.market.b_bps=1 | .fees_bps=10 | .market.slip_bps_est=20')
r2=$(check "$p2")
echo "ER deny: $r2" | jq '.' || true

# 3) Risk deny
export AURORA_DD_DAY_PCT=0.5
p3=$(echo "$base" | jq '.market.pnl_today_pct=-1')
r3=$(check "$p3")
echo "Risk deny: $r3" | jq '.' || true

allow1=$(echo "$r1" | jq -r '.allow')
allow2=$(echo "$r2" | jq -r '.allow')
allow3=$(echo "$r3" | jq -r '.allow')
reason2=$(echo "$r2" | jq -r '.reason')
reason3=$(echo "$r3" | jq -r '.reason')

if [[ "$allow1" == "false" && "$allow2" == "false" && "$reason2" == "expected_return_gate" && "$allow3" == "false" && "$reason3" == *"risk_"* ]]; then
  echo 'QA pretrade order: PASS'; exit 0
else
  echo 'QA pretrade order: FAIL'; exit 1
fi
