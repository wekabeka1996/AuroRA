param(
    [string]$Url = "http://127.0.0.1:8000/pretrade/check"
)

# Compose request body as ordered hashtables for stable JSON
$body = [ordered]@{
  account   = [ordered]@{ mode = "shadow"; gross_exposure_usdt = 0 }
  order     = [ordered]@{ symbol = "BTCUSDT"; side = "LONG"; type = "LIMIT"; qty = 0.001; price = 65000; leverage = 10; time_in_force = "GTC" }
  market    = [ordered]@{ mid = 65000; spread_bps = 5.0 }
  risk_tags = @("scalping", "auto")
  fees_bps  = 1.0
}

$json = $body | ConvertTo-Json -Depth 6

Write-Host "POST $Url" -ForegroundColor Cyan
try {
    $resp = Invoke-RestMethod -Uri $Url -Method Post -ContentType 'application/json' -Body $json
    $resp | ConvertTo-Json -Depth 6
} catch {
    Write-Error $_
    if ($_.Exception.Response -and $_.Exception.Response.GetResponseStream) {
        $reader = New-Object System.IO.StreamReader($_.Exception.Response.GetResponseStream())
        $reader.ReadToEnd()
    }
    exit 1
}
