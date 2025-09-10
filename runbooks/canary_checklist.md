# Aurora Canary Checklist (Release Candidate)

Short, actionable steps for a 30–60 min canary in live/shadow.

## Prereqs
- Config frozen: tag and commit hash noted
- OPS tokens and endpoints available
- Metrics endpoint reachable (Prometheus or /metrics)
- DRY_RUN=false for live; shadow: DRY_RUN=true

## Launch
- Start API (live mode) and Runner (shadow or live) per VS Code tasks:
  - Start API (8080 live)
  - Start Runner with base profile
- Confirm /readiness returns 200 with `Cache-Control: no-store` and stable JSON

## SLA & Latency
- SLI:
  - exec_latency_ms p50<=20ms, p95<=200ms
  - aurora_latency_tick_submit_ms p95<=150ms
- Gate:
  - SLA_LATENCY denies < 5% of decisions

## Edge & Denies
- Metrics to watch:
  - aurora_edge_net_after_tca_bps histogram: mass > 0 bps bucket; tail <= -20 bps minimal
  - aurora_order_denies_total by reason: SPREAD_DENY, EDGE_FLOOR, LOW_PFILL.DENY
- Targets:
  - Deny share total < 40% (shadow OK up to 60%); LOW_PFILL.DENY < 15%
  - EDGE_FLOOR denies correlate with low edge sessions; manual sample check

## p_fill & Routing
- Watch aurora_pfill_predicted histogram: center around 0.4–0.7 in liquid pairs
- ROUTER.DECISION events: verify `p_fill_min`, `why_code`, and `route` consistency
- Sanity: maker selected when (p>=pfill_min and spread<=maker_spread_ok_bps and E_m - E_t >= switch_margin_bps)

## XAI / Observability
- Logs: `logs/<session>/aurora_events.jsonl`
  - Ensure presence of: POLICY.DECISION, ROUTER.DECISION, EXPECTED_NET_REWARD_GATE (if applicable)
- XAI integrity quick-check:
  - Single trace_id per scenario; events ordered by ts; required components present (signal/risk/oms)

## Safety & Rollback
- Stop conditions:
  - Net_after_tca median <= 0 for > 10 min
  - SLA_LATENCY denies spike > 20%
  - SPREAD_DENY > 30% sustained (market issue)
- Actions:
  - Switch Runner to DRY_RUN=true or stop runner
  - Revert to previous tag; open incident note with metrics snapshots

## System-validation quick command (seed + tests + validate)

Run this locally or in CI to perform a self-check before promoting to testnet/live:

```bash
python tools/seed_synthetic_flow.py --out logs/synth.jsonl --seed 1 --scenarios maker,taker,low_pfill,size_zero,sla_deny --n 1 --truncate
python -m pytest tests/system_validation -m "not perf" --maxfail=1
python tools/validate_canary_logs.py \
  --path logs/synth.jsonl \
  --window-mins 5 \
  --p95-latency-ms-max 500 \
  --deny-share-max 0.60 \
  --low-pfill-share-max 0.50 \
  --net-after-tca-median-min 0 \
  --xai-missing-rate-max 0.01 \
  --pfill-median-min 0.40 \
  --pfill-median-max 0.80 \
  --corrupt-rate-max 0.01 \
  --strict-progress-max 0.05
```

## Go / No-Go additions

- p_fill median must be within [0.40, 0.80] across synthetic intents (otherwise investigate p_fill model/calibration).
- corrupt_rate (malformed JSONL lines) must be <= 1% — if exceeded, abort canary and inspect producers/emitter (AuroraEventLogger usage).
 - unprogressed_share (intents that never progressed beyond ORDER.INTENT.RECEIVED) must be <= 5% (use --strict-progress-max). This prevents silent regressions where the pipeline stops early.

## After-Run Sanity
- Export coverage report from CI (>=90%)
- Mutation score floor (>=60%) and not >5% drop vs baseline
- Archive session logs and Prometheus snapshot for postmortem

---
Tips:
- Use scripts/monitor_events.sh to tail key events quickly
- Use tools/auroractl.py one-click for bundled start/stop in shadow
