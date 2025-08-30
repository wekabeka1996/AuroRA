Aurora Project Audit — 2025-08-26

Scope
- Deep read-only audit of structure, interactions, and runtime paths.
- Hardcoded parameters found in code (tests ignored).
- Files and folders not required for production runtime of Aurora API and the bot.
- No code changes were made.

Architecture Overview
- Aurora API: `api/service.py` (FastAPI) exposes `/predict`, `/pretrade/check`, `/posttrade/log`, `/health`, `/metrics`, and protected OPS endpoints (`/liveness`, `/readiness`, `/ops/*`, `/aurora/*`). Uses:
  - Health: `aurora.health.HealthGuard` (latency p95 guard with cooloff/halt).
  - Gates: `core/aurora/pretrade.py` (latency, expected-return, slippage, TRAP).
  - Risk/Governance: `risk.manager.RiskManager`, `aurora.governance.Governance`.
  - Order logging: `core.order_logger.OrderLoggers` (success/failed/denied JSONL).
  - Events: `core.aurora_event_logger.AuroraEventLogger` (JSONL + Prometheus counter hook).
  - Ack tracker: `core.ack_tracker.AckTracker` (ORDER.EXPIRE background scan).
- Bot (WiseScalp integration): `skalp_bot/runner/run_live_aurora.py` streams market via CCXT and calls Aurora pretrade and posttrade endpoints through `skalp_bot/integrations/aurora_gate.py`.
- Exchange adapter: `skalp_bot/exch/ccxt_binance.py` (env-based keys, testnet toggle, futures/spot).
- Config resolution: `common/config.py` (YAML-first with env overrides), `core/env.py` (env defaults).
- Observability: JSONL logs in `logs/<session>/...`, Prometheus at `/metrics`.

Interaction Scheme (ASCII)
```
WiseScalp Runner (skalp_bot/runner/run_live_aurora.py)
    |  market data via CCXT (binance/USDM)
    v
CCXTBinanceAdapter (skalp_bot/exch/ccxt_binance.py)
    |  builds order intent, risk context
    |  HTTP (default 100ms timeout)
    v
AuroraGate (skalp_bot/integrations/aurora_gate.py)
    |  POST /pretrade/check  ----------------------------->  Aurora FastAPI (api/service.py)
    |                                                       - loads YAML cfg + env
    |                                                       - HealthGuard (latency p95)
    |                                                       - Gates: latency/ER/slippage/TRAP
    |                                                       - RiskManager + Governance
    |                                                       - AckTracker (bg)
    |                                                       - Emits events + metrics
    |  <--------------------------- allow/deny + observability
    |
    |  POST /posttrade/log (after trade)
    |  -> order logs JSONL + ORDER.* events + metrics
    |
    +--> Prometheus /metrics (Counter/Gauge/Histogram)
    +--> JSONL logs: logs/<session>/aurora_events.jsonl, orders_*.jsonl
```

Entrypoints & Defaults
- API: `uvicorn api.service:app` (Dockerfile uses `--host 0.0.0.0 --port 8000`).
- Ops CLI: `tools/auroractl.py start-api`, health checks, OPS actions (`cooloff`, `disarm`).
- Bot: `python -m skalp_bot.runner.run_live_aurora` (reads config from `skalp_bot/configs/*.yaml`).

Hardcoded Parameters (files; examples)
- api/service.py
  - `CONFIG_PATH = 'configs/v4_min.yaml'` (file missing in repo; fallback logic loads env/name or {}).
  - Host/port defaults: `host='0.0.0.0'`, `port=8000` (when run as `__main__`).
  - Session/log paths: default under `logs/<timestamp>/` with filenames `aurora_events.jsonl`, `orders_*.jsonl`.
  - Latency guard immediate cutoff: default `30.0 ms` if not configured (`AURORA_LMAX_MS`).
  - HealthGuard thresholds: defaults 30 ms (p95), 60 s window, 120 s cooloff, repeats 2.
  - TRAP defaults from env with fallbacks: z=1.64, cancel_pctl=90, trap_score threshold=0.8.
  - Ack tracker defaults: TTL 300 s, scan period 1 s.
  - OPS auth: default allowlist `['127.0.0.1', '::1']`; token read from `OPS_TOKEN`/`AURORA_OPS_TOKEN`/cfg; strict match.
- aurora_api_lite.py (dev-only)
  - Host `127.0.0.1`, port `8000`. Synthetic responses; no external dependencies.
- skalp_bot/runner/run_live_aurora.py
  - Defaults: `EXCHANGE_TESTNET=true`, `EXCHANGE_USE_FUTURES=true`, `DRY_RUN=false` (overridable by .env).
  - Session dir creation under `logs/<timestamp>/`.
  - Aurora base URL default `'http://127.0.0.1:8000'` when not in YAML.
  - HTTP timeout default `AURORA_HTTP_TIMEOUT_MS=100` (ms).
  - Local limits defaults: `trades_per_minute_limit=10`, `max_symbol_exposure_usdt=1000.0`.
- skalp_bot/integrations/aurora_gate.py
  - Default base URL `'http://127.0.0.1:8037'` (note: inconsistent with others using :8000).
  - `DEFAULT_TIMEOUT_S = 0.010` (10 ms).
  - Fail-open behavior in `shadow/paper` modes on HTTP errors; fail-closed in `prod`.
- tools/auroractl.py
  - Defaults: host `127.0.0.1`, port `8000`; uses `AURORA_OPS_TOKEN`/`OPS_TOKEN` for protected endpoints.
- core/env.py
  - Exchange defaults: `EXCHANGE_ID='binanceusdm'`, `EXCHANGE_TESTNET=true`, `DRY_RUN=true`, `BINANCE_RECV_WINDOW=20000`.
  - Pretrade defaults: `AURORA_PI_MIN_BPS=1.5`, `AURORA_SLIP_FRACTION=0.25`, `AURORA_SPREAD_MAX_BPS=50.0`.
  - Sizing/ops defaults: `AURORA_SIZE_SCALE=0.05`, `AURORA_MAX_CONCURRENT=1`, `AURORA_HTTP_TIMEOUT_MS=120`.
- tools/* (selected)
  - Hardcoded localhost URLs for health/OPS (e.g., `http://127.0.0.1:8000`).

Sensitive Findings
- .env (present in repo root, ignored by git): contains real credentials
  - `BINANCE_API_KEY` and `BINANCE_API_SECRET` have non-placeholder values.
  - Risk: leaking this file would expose exchange account. Keep out of any artifacts and images.
- configs/aurora_config.template.yaml: placeholder `ops_token` documented as dev-only; instructs to prefer `OPS_TOKEN` env in production.

Config/File Inconsistencies
- Inconsistent Aurora base URL defaults:
  - `skalp_bot/integrations/aurora_gate.py` → `http://127.0.0.1:8037`
  - `skalp_bot/runner/run_live_aurora.py` and docs → `http://127.0.0.1:8000`
  - `tools/*` → `http://127.0.0.1:8000`
  Impact: unexpected client failures if default 8037 is used. Prefer unifying on 8000 or config/env-driven.
- `api/service.py` references `configs/v4_min.yaml` by default, but this file is missing. Code falls back to env/name/empty dict, but default naming is misleading.

Files/Dirs Not Required For Production Runtime
- Development/editor/cache
  - `.vscode/`, `.pytest_cache/`, `.gitattributes`, `.pre-commit-config.yaml`.
- Local artifacts and outputs
  - `artifacts/`, `logs/`, `reports/`.
- R&D, docs, roadmaps
  - `archive/`, `docs/`, `Copilot_Master_Roadmap.md`, `ROADMAP_STATUS.md`, `CONTRIBUTING.md`, `CHANGELOG.md`, `README*.md` (keep externally).
- Test and diagnostics
  - `tests/` (excluded by scope), `.diagnose_pretrade.py`, `tools/*_test*`, `tools/run_tests_clean_env.py`.
- Optional tooling (not needed to run API/bot themselves)
  - `tools/` utilities (auroractl useful for ops but not required inside minimal runtime image),
    `tools/canary_harness.py`, `tools/run_canary.py`, `tools/binance_smoke.py`, analysis scripts.
- Alternate/simple API for demo
  - `aurora_api_lite.py` (dev/demo only).
- Packaging/CI scaffolding (optional in minimal image)
  - `Dockerfile`/`docker-compose.yml` (kept if using containers), `setup.py` (if not packaging), `.github/`.
- Monitoring specs (optional but recommended for prod ops)
  - `ops/prometheus_rules.yaml`, `observability/schema.json` (used by linters, not runtime).

Note: Some “not required” items may still be desirable in production environments for ops, CI/CD, and observability. The list above focuses strictly on what the bot and API processes need to execute.

Files With Hardcoded Parameters (summary list)
- `api/service.py`
- `aurora_api_lite.py`
- `core/env.py`
- `core/aurora/pretrade.py` (threshold logic messages)
- `skalp_bot/runner/run_live_aurora.py`
- `skalp_bot/integrations/aurora_gate.py`
- `skalp_bot/exch/ccxt_binance.py`
- `tools/auroractl.py`, `tools/*canary*`, `tools/*smoke*`, `tools/run_canary.py`

Recommendations (non-invasive)
- Unify Aurora base URL defaults (prefer env/YAML, avoid divergent literals).
- Replace `configs/v4_min.yaml` default with an existing default name (or gate entirely via env such as `AURORA_CONFIG`).
- Treat `.env` as local-only; never ship in images or commit. Consider secrets managers for production.
- Review default guard thresholds (latency 30ms, TRAP z=1.64, score=0.8) against current SLOs.
- Confirm fail-open policy in `shadow/paper` fits risk appetite; ensure `prod` mode is fail-closed end-to-end.

Appendix: Key Paths and Metrics
- Logs: `logs/<session>/aurora_events.jsonl`, `orders_success.jsonl`, `orders_failed.jsonl`, `orders_denied.jsonl`.
- Metrics: `aurora_events_emitted_total{code}`, `aurora_orders_success_total`, `aurora_orders_rejected_total`, `aurora_orders_denied_total`, `aurora_ops_auth_fail_total`.

