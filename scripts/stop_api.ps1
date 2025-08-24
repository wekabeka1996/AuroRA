param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

Write-Host "Stopping API on port $Port"
Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {
  $processIdNumber = $_.OwningProcess
  try {
    Stop-Process -Id $processIdNumber -Force -ErrorAction Stop
    Write-Host "Stopped process $processIdNumber"
  } catch {
    Write-Warning ("Failed to stop process {0}: {1}" -f $processIdNumber, $_)
  }
}
$procs = Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'python.exe' -and $_.CommandLine -match 'api[/\\]service.py' }
if (-not $procs) {
  Write-Host "No api/service.py process found." -ForegroundColor Yellow
  exit 0
}
foreach ($p in $procs) {
  Write-Host "Stopping PID $($p.ProcessId) ..."
  try {
    Stop-Process -Id $p.ProcessId -ErrorAction Stop
  } catch {
    Write-Host "Force killing PID $($p.ProcessId)" -ForegroundColor Red
    taskkill /PID $p.ProcessId /F | Out-Null
  }
}
Write-Host "Stopped."
