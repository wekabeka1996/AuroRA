param(
  [int]$Port = 8000,
  [string]$Host = "127.0.0.1"
)

$ErrorActionPreference = 'Stop'

Write-Host "[shim] Delegating to auroractl start-api --port $Port --host $Host"

$repoRoot = Join-Path $PSScriptRoot ".."
Set-Location $repoRoot

$python = "python"
& $python tools/auroractl.py start-api --port $Port --host $Host
exit $LASTEXITCODE
