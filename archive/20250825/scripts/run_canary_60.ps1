param(
  [int]$Minutes = 60,
  [string]$OpsToken = $env:OPS_TOKEN,
  [int]$Port = 8000,
  [string]$ListenHost = '127.0.0.1',
  [string]$RunnerConfig = 'skalp_bot\configs\default.yaml'
)
$ErrorActionPreference = "Stop"

Write-Host "[shim notice] New preferred command: python tools/auroractl.py canary --minutes $Minutes" -ForegroundColor Yellow

function Get-EventsTail {
  param(
    [string]$Path,
    [int]$Count = 10
  )
  if (Test-Path $Path) {
    Write-Host "Last $Count RISK/HEALTH events:"
    # Match AURORA.RISK/HEALTH or plain RISK/HEALTH, tolerant to whitespace
    Get-Content -Path $Path -Tail 500 |
      Select-String -Pattern '"type"\s*:\s*"(AURORA\.)?(RISK|HEALTH)\.' |
      Select-Object -Last $Count |
      ForEach-Object { $_.Line }
  }
}

function Start-LiveRunner {
  param(
    [string]$ConfigPath,
    [ref]$ProcRef,
    [ref]$LogPathRef
  )
  $logsDir = "logs"
  if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }
  $ts = Get-Date -Format 'yyyyMMdd_HHmmss'
  $log = Join-Path $logsDir "live_$ts.log"
  $LogPathRef.Value = $log
  Write-Host "[Runner] Starting WiseScalp LIVE (config=$ConfigPath) -> $log" -ForegroundColor Cyan
  $psi = New-Object System.Diagnostics.ProcessStartInfo
  $psi.FileName = "python"
  # PowerShell 5.1 (Full .NET) не имеет свойства ArgumentList у ProcessStartInfo —
  # используем Arguments с корректным экранированием. В PowerShell Core оставим совместимость.
  try {
    if ($psi.PSObject.Properties.Name -contains 'ArgumentList') {
      $psi.ArgumentList = @("-m", "skalp_bot.scripts.run_live_aurora", $ConfigPath)
    } else {
      $argsList = @("-m", "skalp_bot.scripts.run_live_aurora", $ConfigPath) |
        ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
      $psi.Arguments = ($argsList -join ' ')
    }
  } catch {
    # Fallback на Arguments, если по каким-то причинам доступ к ArgumentList невозможен
    $argsList = @("-m", "skalp_bot.scripts.run_live_aurora", $ConfigPath) |
      ForEach-Object { if ($_ -match '\s') { '"' + $_ + '"' } else { $_ } }
    $psi.Arguments = ($argsList -join ' ')
  }
  $psi.RedirectStandardOutput = $true
  $psi.RedirectStandardError = $true
  $psi.CreateNoWindow = $true
  $psi.UseShellExecute = $false
  $p = New-Object System.Diagnostics.Process
  $p.StartInfo = $psi
  $null = $p.Start()
  $p.BeginOutputReadLine()
  $p.BeginErrorReadLine()
  # Async log pump
  Register-ObjectEvent -InputObject $p -EventName OutputDataReceived -Action { if ($EventArgs.Data) { Add-Content -Path $using:log -Value $EventArgs.Data } } | Out-Null
  Register-ObjectEvent -InputObject $p -EventName ErrorDataReceived -Action { if ($EventArgs.Data) { Add-Content -Path $using:log -Value $EventArgs.Data } } | Out-Null
  $ProcRef.Value = $p
}

function Stop-LiveRunner {
  param([Parameter(Mandatory=$true)] [System.Diagnostics.Process]$Proc)
  if ($Proc -and -not $Proc.HasExited) {
    Write-Host "[Runner] Stopping LIVE runner (PID=$($Proc.Id))" -ForegroundColor Yellow
    try { $Proc.Kill() } catch {}
  }
}

try {
  # Rotate/clear events BEFORE starting API so the run is not polluted by previous logs
  $events = "logs\events.jsonl"
  if (Test-Path $events) {
    try { Remove-Item -Path $events -Force -ErrorAction SilentlyContinue } catch {}
  }

  # Ensure port is free and start API
  if (Test-Path "scripts/stop_api.ps1") { .\scripts\stop_api.ps1 -Port $Port | Out-Null }
  if (Test-Path "scripts/run_api.ps1") {
    powershell -File scripts\run_api.ps1 -Port $Port -ListenHost $ListenHost | Out-Null
  } elseif (Test-Path "scripts/start_api.ps1") {
    .\scripts\start_api.ps1 | Out-Null
  }

  $baseUrl = "http://${ListenHost}:$Port"

  # Run canary harness (pre-check risk window and optional cooloff)
  $harnessCode = 0
  if (Test-Path "tools/canary_harness.py") {
    $argsList = @("--duration-min", $Minutes, "--window-sec", 300, "--base-url", $baseUrl)
    if (-not [string]::IsNullOrWhiteSpace($OpsToken)) {
      $argsList += @("--ops-token", $OpsToken)
    }
    python tools\canary_harness.py @argsList
    $harnessCode = $LASTEXITCODE
    if ($harnessCode -ne 0) {
      Write-Host "Harness signaled stop (risk breach). Continuing to build summary and run gate for artifacts." -ForegroundColor Yellow
    }
  }

  # Decide mode: shadow vs LIVE (prod + DRY_RUN=false)
  $mode = $env:AURORA_MODE
  $dry = $env:DRY_RUN
  $isLive = ($mode -and $mode.ToLower() -eq 'prod' -and $dry -and $dry.ToLower() -in @('false','0','no'))

  if ($isLive) {
    # Start LIVE runner for the duration
    $procRef = [ref]$null
    $logRef = [ref]$null
    Start-LiveRunner -ConfigPath $RunnerConfig -ProcRef $procRef -LogPathRef $logRef
    Write-Host "LIVE runner is running for $Minutes minutes..." -ForegroundColor Green
    Start-Sleep -Seconds ([int]($Minutes * 60))
    Stop-LiveRunner -Proc $procRef.Value
    Write-Host "LIVE runner stopped. Log: $($logRef.Value)" -ForegroundColor Green
  } else {
    # Generate shadow traffic to exercise the gates for the requested duration
    if (Test-Path "tools/smoke_traffic.py") {
      Write-Host "Starting shadow traffic: $Minutes min @ 5 rps → $baseUrl/pretrade/check" -ForegroundColor Cyan
      python tools\smoke_traffic.py --base-url $baseUrl --duration-min $Minutes --rps 5.0
      Write-Host "Shadow traffic finished." -ForegroundColor Green
    } else {
      Write-Warning "tools/smoke_traffic.py not found; proceeding without generating traffic."
    }
  }

  # Build summary
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
