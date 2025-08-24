Param(
  [int]$Port = 8000
)

try {
  $resp = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$Port/health" -TimeoutSec 3 -Method GET
  if ($resp.StatusCode -eq 200) {
    Write-Host "API healthy on port $Port" -ForegroundColor Green
    exit 0
  } else {
    Write-Host "API unhealthy: $($resp.StatusCode)" -ForegroundColor Red
    exit 1
  }
} catch {
  Write-Host "API health check failed: $($_.Exception.Message)" -ForegroundColor Red
  exit 1
}
