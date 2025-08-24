param(
  [int]$Port = 8000,
  [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = 'Stop'

function Get-PythonExe {
  $venvPy = Join-Path $PSScriptRoot "..\.venv\Scripts\python.exe"
  if (Test-Path $venvPy) { return $venvPy }
  return "python"
}

$python = Get-PythonExe

# Ensure we're in repo root
Set-Location (Join-Path $PSScriptRoot "..")

# Build uvicorn command
$uvicornArgs = "-m uvicorn api.service:app --host $Host --port $Port --log-level info"

Write-Host "Starting Aurora API: http://$Host:$Port" -ForegroundColor Cyan

# Start in separate window to avoid being killed when this terminal runs other commands
Start-Process -FilePath $python -ArgumentList $uvicornArgs -WindowStyle Normal

Start-Sleep -Seconds 2

try {
  $resp = Invoke-WebRequest -Uri "http://$Host:$Port/health" -Method GET -TimeoutSec 3
  if ($resp.StatusCode -eq 200) {
    Write-Host "Aurora API is up at http://$Host:$Port (open /docs in browser)" -ForegroundColor Green
    exit 0
  }
} catch {
  Write-Warning "Aurora API not responding yet. It may still be initializing. Try opening http://$Host:$Port/docs in your browser."
  exit 1
}
