# Aurora — Unified Trading System

This repository contains the Aurora core API and WiseScalp integration.

## Repo layout (high level)
- `api/` — FastAPI service, health/ops endpoints, pretrade checks
- `aurora/` — health guards, utilities
- `common/` — configs, events
- `core/` — env, loggers, scalper components
- `risk/` — risk manager
- `skalp_bot/` — WiseScalp integration & runners
- `tools/` — operational CLIs, harnesses
- `docs/` — specs, runbooks
- `logs/`, `artifacts/` — runtime outputs (ignored), kept with `.keep`
- `archive/YYYYMMDD/` — archived R&D with `ARCHIVE_INDEX.md`

See `Copilot_Master_Roadmap.md` for the SSOT roadmap.

## Tools

- `tools/auroractl.py` — unified CLI for config and ops.
- `tools/metrics_summary.py` — summarize logs into reports.
- `tools/lifecycle_audit.py` — build order lifecycle graphs and anomalies; run: `python tools/lifecycle_audit.py`.


## Ops & Tokens + Event Codes

### Ops & Security (X-OPS-TOKEN)

- Canonical env var: `OPS_TOKEN` (alias `AURORA_OPS_TOKEN` is supported but emits WARN event `OPS.TOKEN.ALIAS_USED`).
- Protected endpoints: `/liveness`, `/readiness`, `/ops/rotate_token` (metrics exposed at `/metrics`).
- Examples:

```bash
# Metrics (header optional for local dev)
curl -s -H "X-OPS-TOKEN: $OPS_TOKEN" http://localhost:8000/metrics

# Token rotation (old token stops working)
curl -s -X POST -H "X-OPS-TOKEN: $OPS_TOKEN" \
	http://localhost:8000/ops/rotate_token -d '{"new_token":"REDACTED_32+"}' -H 'content-type: application/json'
```

### Logs and retention

- Orders: `logs/orders_success.jsonl`, `logs/orders_failed.jsonl`, `logs/orders_denied.jsonl`
- Events: `logs/aurora_events.jsonl`
- Rotation: daily + size, gzip, retention 7 days (configurable via `AURORA_LOG_RETENTION_DAYS`, `AURORA_LOG_ROTATE_MAX_MB`).

### Event codes (dot-canon)

- ORDER.*: `SUBMIT`, `ACK`, `PARTIAL`, `FILL`, `REJECT`, `CANCEL.REQUEST`, `CANCEL.ACK`, `EXPIRE`
- GOVERNANCE.*: `ALLOW`, `DENY`
- HEALTH.*: `LATENCY_HIGH`, `LATENCY_P95_HIGH`
- OPS.*: `TOKEN.ALIAS_USED`, `TOKEN_ROTATE`, `RESET`
- AURORA.*: `EXPECTED_RETURN_*`, `SLIPPAGE_GUARD`, `COOL_OFF`, `ARM_STATE`, `ESCALATION`
- RISK.*: `DENY`, `UPDATE`
- Normalization: only `ORDER_* → ORDER.*`; other codes are unchanged.

### Metrics (Prometheus)

- Events: `aurora_events_emitted_total{code}`
- Orders: `aurora_orders_success_total`, `aurora_orders_rejected_total`, `aurora_orders_denied_total`
- OPS: `aurora_ops_auth_fail_total`, `aurora_ops_token_rotations_total`
- Handy queries:

```promql
# Conversion (10m)
rate(aurora_orders_success_total[10m])
/
rate(aurora_orders_success_total[10m] + aurora_orders_rejected_total[10m] + aurora_orders_denied_total[10m])

# Reject spike (5m)
increase(aurora_events_emitted_total{code="ORDER.REJECT"}[5m])
```

### Lifecycle & Latency

- FSM: `PREPARED→SUBMITTED→ACK→PARTIAL/FILL|CANCEL|REJECT|EXPIRE`
- Latency report (p50/p95/p99) from correlator: `submit→ack`, `ack→done`.

### Kill‑switch (recommended thresholds)

```yaml
gates:
	spread_bps_max: 8.0
	vol_std_bps_max: 60.0
	latency_ms_max: 150
	dd_day_pct_max: 5.0
	cvar_day_pct_max: 10.0
killswitch:
	window_trades: 50
	max_reject_rate_pct: 35
	max_denied_rate_pct: 50
	action: HALT_AND_ALERT
```

### Testnet vs Prod

- Testnet: you may enable cancel stub (emits `ORDER.CANCEL.REQUEST/ACK`).
	- `AURORA_CANCEL_STUB=true`, `AURORA_CANCEL_STUB_EVERY_TICKS=120`
- Prod: `AURORA_CANCEL_STUB=false` (default).

### Quickstart

```bash
# Config validator
python tools/auroractl.py config-validate --name master_config_v2

# API (includes background AckTracker)
python tools/auroractl.py start-api

# Runner (WiseScalp)
python -m skalp_bot.runner.run_live_aurora

# Metrics summary
python tools/metrics_summary.py --window-sec 3600 --out reports/summary_gate_status.json
```

### Troubleshooting

- Orders success counter not increasing → ensure order loggers are initialized inside endpoints (`/pretrade/check`, `/posttrade/log`) — counters increment only after successful writes into `orders_*.jsonl`.
- Events not written → check `logs/` permissions and path; verify `aurora_events.jsonl` is created.
- Metrics look empty → include `X-OPS-TOKEN` header; alias usage will emit `OPS.TOKEN.ALIAS_USED`.


## Post-merge quick actions

```bash
# Tag and release
git tag -a v0.4-beta -m "Aurora+WiseScalp: ORDER.*, AckTracker, Metrics v1, OPS security"
git push origin v0.4-beta

# Targeted tests
pytest -q tests/events/test_events_emission.py \
					tests/events/test_events_rotation.py \
					tests/metrics/test_metrics_summary.py \
					tests/test_order_counters.py \
					tests/events/test_late_ack_and_partial_cancel.py

# Smoke
curl -s -H "X-OPS-TOKEN: $OPS_TOKEN" http://localhost:8000/metrics | \
	grep -E "aurora_events_emitted_total|aurora_orders_.*_total"
python tools/metrics_summary.py --window-sec 600 --out reports/summary_gate_status.json
```
