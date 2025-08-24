param(
    [string]$ConfigPath = 'skalp_bot\configs\default.yaml',
    [int]$Tail = 80
)

$ErrorActionPreference = 'Stop'

# Resolve repo root from this script location
$repoRoot = Resolve-Path (Join-Path $PSScriptRoot '..\..')
Set-Location $repoRoot

# Python path
$py = Join-Path $repoRoot '.venv\Scripts\python.exe'
if (!(Test-Path $py)) {
    $py = 'python'
}

# Logs (absolute paths)
if (!(Test-Path -Path 'logs')) { New-Item -ItemType Directory -Path 'logs' | Out-Null }
$apiOutRel = "logs/api_out_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$apiErrRel = "logs/api_err_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$runLogRel = "logs/shadow_$(Get-Date -Format 'yyyyMMdd_HHmmss').log"
$apiOut = Join-Path $repoRoot $apiOutRel
$apiErr = Join-Path $repoRoot $apiErrRel
$runLog = Join-Path $repoRoot $runLogRel

Write-Host "[AURORA] Starting API (uvicorn) ..."
# Try to free port 8000 if already in use
$existing = (& netstat -ano | Select-String ':8000' | ForEach-Object { ($_ -split '\s+')[-1] } | Where-Object { $_ -match '^[0-9]+$' } | Select-Object -First 1)
if ($existing) {
    try { & taskkill /PID $existing /F | Out-Null } catch {}
}

# Start API in background (separate logs for stdout/stderr)
Start-Process -WorkingDirectory $repoRoot -WindowStyle Hidden -FilePath $py -ArgumentList '-m','uvicorn','api.service:app','--host','127.0.0.1','--port','8000' -RedirectStandardOutput $apiOut -RedirectStandardError $apiErr | Out-Null
Start-Sleep -Seconds 2

# Health probe (up to ~15s)
$ok=$false
for ($i=0; $i -lt 15; $i++) {
    try {
        $resp = Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/healthz -TimeoutSec 1
        if ($resp.StatusCode -ge 200) { $ok=$true; break }
    } catch {}
    Start-Sleep -Seconds 1
}
if (-not $ok) {
    Write-Host "[AURORA] API_HEALTHZ:FAIL" -ForegroundColor Red
    if (Test-Path $apiErr) { Write-Host '--- api_err ---'; Get-Content -Tail 120 $apiErr }
    if (Test-Path $apiOut) { Write-Host '--- api_out ---'; Get-Content -Tail 120 $apiOut }
    exit 1
}
Write-Host "[AURORA] API_HEALTHZ:OK" -ForegroundColor Green

# Start runner in background job, capture all streams to a single file
Write-Host "[WISESCALP] Starting shadow runner ..."
$env:AURORA_MODE = 'shadow'
Start-Job -ScriptBlock {
    param($py,$cfg,$log,$cwd)
    try { Set-Location $cwd } catch {}
    $env:AURORA_MODE='shadow'
    & $py -m skalp_bot.scripts.run_live_aurora $cfg *>$log
} -ArgumentList $py,$ConfigPath,$runLog,$repoRoot | Out-Null

# Wait up to 10s for log file to appear
$tries = 0
while (-not (Test-Path $runLog) -and $tries -lt 10) { Start-Sleep -Seconds 1; $tries++ }

if (Test-Path $runLog) {
    Write-Host "[TAIL] $runLog" -ForegroundColor Cyan
    Get-Content -Tail $Tail $runLog
} else {
    Write-Host "[AURORA] RUN_LOG_MISSING ($runLog)" -ForegroundColor Yellow
}

Write-Host "[AURORA] Done. Use Get-Job to see background jobs. To stop: Get-Job | Stop-Job; Or close the terminal." -ForegroundColor DarkGray
