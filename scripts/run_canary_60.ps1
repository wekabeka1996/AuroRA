param(
  [int]$Minutes = 60,
  [string]$OpsToken = $env:OPS_TOKEN,
  [int]$Port = 8000,
  [string]$ListenHost = '127.0.0.1'
)
$ErrorActionPreference = "Stop"

function Get-EventsTail {
  param(
    [string]$Path,
    [int]$Count = 10
  )
  if (Test-Path $Path) {
    Write-Host "Last $Count RISK/HEALTH events:"
    Get-Content -Path $Path -Tail 500 | Select-String -Pattern '"type":"(RISK|HEALTH)\.' | Select-Object -Last $Count | ForEach-Object { $_.Line }
  }
}

try {
  # Ensure port is free and start API
  if (Test-Path "scripts/stop_api.ps1") { .\scripts\stop_api.ps1 -Port $Port | Out-Null }
  if (Test-Path "scripts/run_api.ps1") {
    powershell -File scripts\run_api.ps1 -Port $Port -ListenHost $ListenHost | Out-Null
  } elseif (Test-Path "scripts/start_api.ps1") {
    .\scripts\start_api.ps1 | Out-Null
  }

  $baseUrl = "http://${ListenHost}:$Port"

  # Run canary harness (pre-check risk window and optional cooloff)
  if (Test-Path "tools/canary_harness.py") {
    python tools\canary_harness.py --duration-min $Minutes --window-sec 300 --ops-token $OpsToken --base-url $baseUrl
    if ($LASTEXITCODE -ne 0) {
      Write-Host "Harness signaled stop (risk breach). Aborting run." -ForegroundColor Yellow
      exit $LASTEXITCODE
    }
  }

  # Build summary
  $events = "logs\events.jsonl"
  $summary = "artifacts\canary_${Minutes}min_summary.md"
  python tools\canary_summary.py --events $events --out-md $summary --out-ts reports\latency_p95_timeseries.csv --out-flow reports\escalations_flow.md

  # Run gate
  python tools\summary_gate.py --summary $summary --events $events --strict --time-window-last 300 --status-out reports\summary_gate_status.json
  $code = $LASTEXITCODE

  # Print concise smoke metrics line
  if (Test-Path "tools/print_smoke_metrics.py") {
    python tools\print_smoke_metrics.py --events $events --summary $summary --latency-ts reports\latency_p95_timeseries.csv
  }

  if ($code -ne 0) {
    Get-EventsTail -Path $events -Count 10
  }

  exit $code
}
finally {
  if (Test-Path "scripts/stop_api.ps1") { .\scripts\stop_api.ps1 -Port $Port }
}
