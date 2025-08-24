param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

if ($null -eq $env:PRETRADE_ORDER_PROFILE) { $env:PRETRADE_ORDER_PROFILE = 'er_before_slip' }
if ($null -eq $env:AURORA_MODE) { $env:AURORA_MODE = 'shadow' }

Write-Host "Starting API (mode=$($env:AURORA_MODE), order_profile=$($env:PRETRADE_ORDER_PROFILE), port=$Port)"

# Check port availability
$inUse = (netstat -ano | findstr ":$Port" | Measure-Object).Count -gt 0
if ($inUse) {
  Write-Host "Port $Port is in use. Use scripts/stop_api.ps1 -Port $Port to stop existing service." -ForegroundColor Yellow
  exit 1
}

# Delegate to the unified runner (does uvicorn + health check)
powershell -File scripts/run_api.ps1 -Port $Port
