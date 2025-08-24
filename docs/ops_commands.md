## Latency guard and OPS endpoints

- POST /ops/cooloff/{sec} — start or extend cooloff timer by given seconds.
- POST /ops/reset — clear escalations (cooloff, halt) and warn counters.
- POST /aurora/arm — arm the guard (fail-closed enforced).
- POST /aurora/disarm — disarm the guard (pretrade will block with reason=disarmed).

Config knobs (configs/v4_min.yaml → aurora.*):
- latency_guard_ms: p95 threshold in ms
- latency_window_sec: window for aggregation
- cooloff_base_sec: duration of cooloff on a WARN
- halt_threshold_repeats: WARN repeats in 5m to trigger HALT

Environment overrides:
- AURORA_LATENCY_GUARD_MS, AURORA_LATENCY_WINDOW_SEC, AURORA_COOLOFF_SEC, AURORA_HALT_THRESHOLD_REPEATS

Notes:
- Endpoints are idempotent; repeated calls maintain state without duplication.
- Events are logged to logs/events.jsonl with types AURORA.COOL_OFF, OPS.RESET, AURORA.ARM_STATE, AURORA.ESCALATION.

# Ops commands and toggles

## Toggle TRAP guard

Default (v4_min): guards.trap_guard_enabled: false

- Enable both TRAP gates (z-score and score-based):
  - PowerShell:
    - `$env:TRAP_GUARD='on'`
  - Bash:
    - `export TRAP_GUARD=on`

- Disable:
  - PowerShell:
    - `$env:TRAP_GUARD='off'`
  - Bash:
    - `export TRAP_GUARD=off`

Optional thresholds:
- `AURORA_TRAP_Z_THRESHOLD` (default 1.64)
- `AURORA_TRAP_CANCEL_PCTL` (default 90)
- `AURORA_TRAP_THRESHOLD` for score-gate (default 0.8)

## Latency guard
- `AURORA_LMAX_MS` caps single-request latency guard (default 30ms)
- See TASK-04 for p95 escalations (coming): /ops endpoints for cooloff/halt/disarm

## Risk endpoints

All endpoints require header `X-OPS-TOKEN`.

PowerShell:

```
$Headers = @{ 'X-OPS-TOKEN' = $env:AURORA_OPS_TOKEN }
Invoke-RestMethod -Method Get -Uri 'http://127.0.0.1:8000/risk/snapshot' -Headers $Headers
Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:8000/risk/set' -Headers $Headers -Body (@{ dd_day_pct=3; max_concurrent=4; size_scale=0.5 } | ConvertTo-Json) -ContentType 'application/json'
```

curl:

```
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" http://127.0.0.1:8000/risk/snapshot
curl -H "X-OPS-TOKEN: $AURORA_OPS_TOKEN" -H 'Content-Type: application/json' -d '{"dd_day_pct":3,"max_concurrent":4,"size_scale":0.5}' http://127.0.0.1:8000/risk/set
```

Notes:
- ENV overrides take precedence over YAML for runtime toggles like `TRAP_GUARD`, `AURORA_*`, and `PRETRADE_ORDER_PROFILE`.
