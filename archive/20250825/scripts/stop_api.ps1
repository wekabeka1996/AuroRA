param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

Write-Host "[shim] Delegating to auroractl stop-api --port $Port"

$repoRoot = Join-Path $PSScriptRoot ".."
Set-Location $repoRoot

$python = "python"
& $python tools/auroractl.py stop-api --port $Port
exit $LASTEXITCODE
