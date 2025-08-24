# Pre-trade pipeline and API contract

Order (frozen):

latency (threshold + p95 escalations) → TRAP → expected_return → slippage → risk caps → SPRT → spread

Feature flag to switch slippage vs expected_return:

- YAML: `pretrade.order_profile: er_before_slip | slip_before_er`
- ENV override: `PRETRADE_ORDER_PROFILE` (ENV has priority)

Response schema highlights:

- `allow: bool`
- `reason: string` — first decisive block reason
- `risk_scale: float` in [0,1]
- `observability: { reasons: string[], latency_ms: float, trap: {...}, sprt: {...}, risk: {...} }`

ENV precedences over YAML (selected):

- `TRAP_GUARD` on/off overrides `guards.trap_guard_enabled`
- `AURORA_*` (latency guard, pi_min_bps, slip eta, etc.)
- `PRETRADE_ORDER_PROFILE`

OPS endpoints (token required in `X-OPS-TOKEN`):

PowerShell examples:

```
$Headers = @{ 'X-OPS-TOKEN' = $env:AURORA_OPS_TOKEN }
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/risk/snapshot' -Headers $Headers
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/risk/set' -Headers $Headers -Body (@{ dd_day_pct=3; size_scale=0.8 } | ConvertTo-Json) -ContentType 'application/json'
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/ops/cooloff/300' -Headers $Headers
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/ops/reset' -Headers $Headers
```

curl examples:

```
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" http://127.0.0.1:8000/risk/snapshot
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" -H 'Content-Type: application/json' -d '{"dd_day_pct":3,"size_scale":0.8}' http://127.0.0.1:8000/risk/set
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" -X POST http://127.0.0.1:8000/ops/cooloff/300
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" -X POST http://127.0.0.1:8000/ops/reset
```
