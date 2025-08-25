$ErrorActionPreference = 'Stop'

function Invoke-Check($payload) {
  $uri = 'http://127.0.0.1:8000/pretrade/check'
  $r = Invoke-RestMethod -Method Post -Uri $uri -Body ($payload | ConvertTo-Json -Depth 5) -ContentType 'application/json'
  return $r
}

# Base payload
$base = @{ account=@{ mode='shadow' }; order=@{ symbol='BTCUSDT'; side='buy'; qty=1; base_notional=100 }; market=@{ latency_ms=5; slip_bps_est=0.5; a_bps=10; b_bps=20; score=0.5; mode_regime='normal'; spread_bps=5; trap_cancel_deltas=@(0,0); trap_add_deltas=@(0,0); trap_trades_cnt=10 }; fees_bps=0.1 }

# 1) TRAP deny
$env:TRAP_GUARD = 'on'
$p1 = $base | ConvertTo-Json -Depth 5 | ConvertFrom-Json
$p1.market.trap_cancel_deltas = @(100,100)
$p1.market.trap_add_deltas = @(0.1,0.1)
$r1 = Invoke-Check $p1
Write-Host "TRAP deny: allow=$($r1.allow) reason=$($r1.reason)"

# 2) Expected return deny
Remove-Item Env:TRAP_GUARD -ErrorAction Ignore
$p2 = $base | ConvertTo-Json -Depth 5 | ConvertFrom-Json
$p2.market.b_bps = 1
$p2.fees_bps = 10
$p2.market.slip_bps_est = 20
$r2 = Invoke-Check $p2
Write-Host "ER deny: allow=$($r2.allow) reason=$($r2.reason)"

# 3) Risk deny (dd_day)
$env:AURORA_DD_DAY_PCT = '0.5'
$p3 = $base | ConvertTo-Json -Depth 5 | ConvertFrom-Json
$p3.market.pnl_today_pct = -1.0
$r3 = Invoke-Check $p3
Write-Host "Risk deny: allow=$($r3.allow) reason=$($r3.reason)"

if (-not $r1.allow -and $r1.reason -like 'trap_*' -and -not $r2.allow -and $r2.reason -eq 'expected_return_gate' -and -not $r3.allow -and $r3.reason -like 'risk_*') {
  Write-Host 'QA pretrade order: PASS'; exit 0
} else {
  Write-Host 'QA pretrade order: FAIL'; exit 1
}
