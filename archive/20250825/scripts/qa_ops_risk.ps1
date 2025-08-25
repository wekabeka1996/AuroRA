$ErrorActionPreference = 'Stop'

if (-not $env:AURORA_OPS_TOKEN) { Write-Host 'AURORA_OPS_TOKEN not set'; exit 1 }
$Headers = @{ 'X-OPS-TOKEN' = $env:AURORA_OPS_TOKEN }

function Get-Risk { Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/risk/snapshot' -Headers $Headers }
function Set-Risk($body) { Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/risk/set' -Headers $Headers -Body ($body | ConvertTo-Json) -ContentType 'application/json' }

$s1 = Get-Risk
Write-Host "Snapshot1: " ($s1 | ConvertTo-Json -Depth 5)

$upd = @{ dd_day_pct = 3; max_concurrent = 5; size_scale = 0.7 }
$s2 = Set-Risk $upd
Write-Host "After set: " ($s2 | ConvertTo-Json -Depth 5)

$s3 = Get-Risk
Write-Host "Snapshot2: " ($s3 | ConvertTo-Json -Depth 5)

if ($s3.risk.dd_day_pct -eq 3 -and $s3.risk.max_concurrent -eq 5 -and $s3.risk.size_scale -eq 0.7) { Write-Host 'QA ops risk: PASS'; exit 0 } else { Write-Host 'QA ops risk: FAIL'; exit 1 }
