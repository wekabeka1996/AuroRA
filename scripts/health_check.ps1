Param(
  [int]$Port = 8000
)

$ErrorActionPreference = 'Stop'

Write-Host "[shim] Delegating to auroractl health --port $Port"
$repoRoot = Join-Path $PSScriptRoot ".."
Set-Location $repoRoot
$python = "python"
& $python tools/auroractl.py health --port $Port
exit $LASTEXITCODE
