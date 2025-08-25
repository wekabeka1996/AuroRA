# Copilot Instructions for this Repo (Aurora × OBI‑Scalper)

Purpose: help AI agents be productive immediately. Focus on THIS codebase’s architecture, workflows, and conventions.

## Big picture
- Two main layers:
  - Aurora service (FastAPI) = watchdog, health/metrics, pre-trade gate and post-trade log.
    - Key: `api/service.py` exposes `/health`, `/metrics`, `/pretrade/check`, `/posttrade/log`.
  - Scalper runner (WiseScalp) = microstructure alpha + execution, calling Aurora gate before orders.
    - Legacy path: `skalp_bot/runner/run_live_aurora.py`, features in `skalp_bot/core/signals.py`, exchange in `skalp_bot/exch/ccxt_binance.py`.
- New v4‑min core (R1 work packages) lives under `core/` and will gradually replace bits of `skalp_bot/`:
  - `core/scalper/` (features, calibrator, traps, sprt), `core/aurora/` (pretrade gates/policy), `common/` (events, config), `configs/v4_min.yaml`.
- Data/telemetry:
  - Prometheus at `/metrics` (see `monitoring/`), JSONL event bus: `logs/events.jsonl` via `common/events.py` (structlog friendly).

## Critical workflows
 - Install + tests (Windows PowerShell):
  - `python -m pip install -r requirements.txt`
  - `python -m pip install -r requirements-dev.txt`
  - Run targeted tests to avoid legacy name clash: `pytest -q tests\unit\test_binance_tfi.py tests\unit\test_calibrator.py`
- API + monitoring via Docker:
  - `docker compose up --build -d` → API http://127.0.0.1:8000, Prometheus :9090, Grafana :3000.
- Local API (no Docker):
  - `python api/service.py` (uvicorn embedded in file) → verify `/health` and `/metrics`.
- Runner (shadow/paper):
  - Set `.env` (see `.env.example`): BINANCE_API_KEY/SECRET, AURORA_MODE=shadow.
  - Start runner (reads `skalp_bot/configs/default.yaml`): module `skalp_bot.runner.run_live_aurora`.
  - On Windows prefer a small PS script over one‑liners to avoid quoting issues.

Note: this developer environment uses bash as the default interactive shell; prefer providing bash-compatible examples for shell commands. PowerShell-specific notes are included above for Windows users.

## Project‑specific conventions
- Config‑driven:
  - Legacy runner: `skalp_bot/configs/default.yaml` (exchange/testnet/futures, risk/execution, aurora gate URL).
  - New core: `configs/v4_min.yaml` (aurora.dd_day_limit, risk.pi_min_bps, slippage.eta_fraction_of_b, logging.path/level).
- Pre‑trade contract (service ⇄ runner):
  - Runner must call `/pretrade/check` with extended payload (latency, slip estimate, p_tp, e_pi_bps, regime, sprt_llr) before placing orders.
  - Service returns allow/max_qty/reasons and may enforce cooloff/halt (prod = fail‑closed).
- Expected‑return gate (R1):
  - Use `core/scalper/calibrator.py` → `predict_p(score)` and `e_pi_bps(CalibInput)`; allow only if `E[Π] > risk.pi_min_bps`.
  - If sklearn is missing, calibrator falls back to Platt sigmoid.
- Binance trade semantics (HOTFIX):
  - `isBuyerMaker=True ⇒ SELL aggressor`, `False ⇒ BUY` (see `core/scalper/features.py::tfi_from_binance_trades`).
- Events/logging:
  - Prefer JSONL events via `common/events.EventEmitter` to `logs/events.jsonl`; keep messages short and structured.
- Don’t fight Windows PowerShell quoting—use here‑strings or dedicated scripts for JSON payloads.

## Integration points
- Aurora <-> Runner: HTTP calls to `/pretrade/check` and `/posttrade/log` (see `skalp_bot/integrations/aurora_gate.py`).
- Exchange: CCXT Binance adapter `skalp_bot/exch/ccxt_binance.py` (supports testnet/futures, recvWindow, time‑diff adjust; picks keys from `.env`).
- Monitoring: `monitoring/prometheus.yml`, `monitoring/aurora_dashboard.json`.

## When adding features
- Put new guards/gates into `core/aurora/pretrade.py` and expose their observability in the pretrade response.
- Put microstructure/alpha logic into `core/scalper/*` (e.g., SPRT/TRAP/toxicity), keep functions pure and streaming‑friendly.
- Log critical decisions as events (types from spec: POLICY.*, AURORA.*, EXEC.*, HEALTH.*) into JSONL.
- Update configs under `configs/` or `skalp_bot/configs/` and thread values down rather than hardcoding.

## Useful file map
- API: `api/service.py`
- Runner: `skalp_bot/runner/run_live_aurora.py`
- Features: `skalp_bot/core/signals.py` (legacy), `core/scalper/features.py` (new)
- Calibrator: `core/scalper/calibrator.py`
- Gates: `core/aurora/pretrade.py`
- Exchange: `skalp_bot/exch/ccxt_binance.py`
- Configs: `skalp_bot/configs/default.yaml`, `configs/v4_min.yaml`
- Events: `common/events.py`

If anything above is unclear, open an issue and tag with AURORA-SCALPER to refine these instructions.

## Roadmap and work journal
- Primary roadmap/spec to follow: `vers_3.md` at repo root. Treat it as the source of truth for scope, WPs, tests, and rollout.
- After completing any todo/task from the roadmap, append a short entry to the agent journal at `docs/agent_journal.md` with:
  - timestamp, task/todo id, files touched, summary of changes, quick test status.
  - keep entries concise; one bullet per completion is fine.