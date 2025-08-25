# Requires: Python venv activated or python available on PATH
# Purpose: Start WiseScalp runner in shadow mode and tail the log safely on Windows
# Usage examples:
#   .\scripts\start_runner_shadow.ps1
#   .\scripts\start_runner_shadow.ps1 -ConfigPath "skalp_bot\configs\default.yaml" -Tail 100
param(
    [string]$ConfigPath = "skalp_bot\configs\default.yaml",
    [int]$Tail = 50,
    [switch]$NoTail
)

$ErrorActionPreference = 'Stop'

# Ensure workspace root
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir '..')

# Prepare logs directory
$logsDir = "logs"
if (-not (Test-Path $logsDir)) { New-Item -ItemType Directory -Path $logsDir | Out-Null }

# Set env for shadow mode if not provided
if (-not $env:AURORA_MODE) { $env:AURORA_MODE = 'shadow' }

# Stop previous background job if tracked in global var
if ($global:runnerJob -and -not $global:runnerJob.HasExited) {
    try { $global:runnerJob.Kill() } catch { }
}

# Compose log file name
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$log = Join-Path $logsDir "shadow_$ts.log"

# Start the runner
Write-Host "[Runner] Starting WiseScalp in shadow mode..."
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = "python"
$psi.ArgumentList = @("-m", "skalp_bot.scripts.run_live_aurora", $ConfigPath)
$psi.RedirectStandardOutput = $true
$psi.RedirectStandardError = $true
$psi.CreateNoWindow = $true
$psi.UseShellExecute = $false
$psi.WorkingDirectory = (Get-Location).Path
$global:runnerJob = New-Object System.Diagnostics.Process
$global:runnerJob.StartInfo = $psi

# Redirect output to log asynchronously
$stdOutEvent = Register-ObjectEvent -InputObject $global:runnerJob -EventName OutputDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -Path $using:log -Value $EventArgs.Data }
}
$stdErrEvent = Register-ObjectEvent -InputObject $global:runnerJob -EventName ErrorDataReceived -Action {
    if ($EventArgs.Data) { Add-Content -Path $using:log -Value $EventArgs.Data }
}

$null = $global:runnerJob.Start()
$global:runnerJob.BeginOutputReadLine()
$global:runnerJob.BeginErrorReadLine()

Start-Sleep -Seconds 2

if (-not $NoTail) {
    Write-Host "[Runner] Tailing $Tail lines of $log (Ctrl+C to stop tail)..."
    try {
        Get-Content -Path $log -Tail $Tail -Wait
    } catch {
        Write-Warning "Failed to tail log: $_"
    }
} else {
    Write-Host "[Runner] Started. Logs: $log"
}
