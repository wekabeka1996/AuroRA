# AURORA v1.2 (Production-Ready Skeleton)

[![canary](https://github.com/${GITHUB_REPOSITORY}/actions/workflows/canary.yml/badge.svg)](https://github.com/${GITHUB_REPOSITORY}/actions/workflows/canary.yml)

This repository implements the AURORA concept (teacher–student, certification, regime-aware) with a working API and training/inference pipelines.

## Quick start
## Aurora CLI (auroractl)

Unified cross‑platform CLI lives in `tools/auroractl.py` (Typer). Examples:

- Start API: `python tools/auroractl.py start-api --host 127.0.0.1 --port 8000`
- Stop API: `python tools/auroractl.py stop-api`
- Health probe: `python tools/auroractl.py health --port 8000`
- Canary: `python tools/auroractl.py canary --minutes 60`
- Smoke: `python tools/auroractl.py smoke [--public-only]`
- Testnet cycle: `python tools/auroractl.py testnet --minutes 5 [--preflight/--no-preflight]`
- Wallet audit: `python tools/auroractl.py wallet-check`
- Metrics: `python tools/auroractl.py metrics --window-sec 3600` (поддерживает выражения: `--window-sec 720*60`)
- Disarm: `python tools/auroractl.py disarm` (requires `AURORA_OPS_TOKEN`)
- Cooloff: `python tools/auroractl.py cooloff --sec 120` (requires `AURORA_OPS_TOKEN`)
- One‑click orchestrator:
	- Testnet: `python tools/auroractl.py one-click --mode testnet --minutes 15 --preflight`
	- Live: `python tools/auroractl.py one-click --mode live --minutes 15 --preflight`
	- Makefile shortcuts: `make one-click-testnet` / `make one-click-live`
	- Пайплайн: wallet‑check → (опционально docker compose up) → start‑api → health wait → canary → metrics → stop‑api

Environment is loaded from `.env` by default (see `.env.example`). Key variables:

- `AURORA_MODE` (prod|shadow|dev), `DRY_RUN` (0/1),
- `EXCHANGE_TESTNET` (0/1), `EXCHANGE_USE_FUTURES` (0/1), `EXCHANGE_ID` (default `binanceusdm`),
- `BINANCE_API_KEY`, `BINANCE_API_SECRET`, `BINANCE_RECV_WINDOW`.

Wallet audit behavior (exit codes):

- 0: OK (report saved to `artifacts/wallet_check.json`)
- 2: Missing required keys for live check
- 3: Insufficient or zero balance (live only)
- 4: Withdrawals disabled for USDT (live only)
- 1: Unexpected error

Metrics aggregates `logs/events.jsonl` and writes:

- `reports/summary_gate_status.json`
- `artifacts/canary_summary.md`
- `artifacts/latency_p95_timeseries.csv` (columns: `ts,value`)

If `PUSHGATEWAY_URL` is set, a minimal exposition is POSTed for quick dashboards.

Makefile is provided for convenience (Linux/macOS). On Windows, call `python tools/auroractl.py ...` directly.


- Build and run API with Prometheus and Grafana:

```bash
# Build API image and start stack
docker compose up --build -d

# API: http://localhost:8000/docs
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000 (create a dashboard and add Prometheus datasource)
```

- Run tests locally:
```bash
pip install -r requirements.txt
pip install -r requirements-dev.txt
pytest -q
```

## Data: build a local dataset (Binance)

Requires: ccxt, pyarrow (already in requirements.txt). On Windows PowerShell:

```powershell
# Install dependencies
pip install -r requirements.txt

# Build dataset from Binance (UTC times)
python scripts/build_dataset.py --symbol BTC/USDT --timeframe 1h --start 2023-01-01 --end 2024-01-01 --outdir data/processed

# Check saved files
Get-ChildItem data/processed
```

Notes:
- Public market data for spot candles usually doesn't require API keys, but if you set BINANCE keys in the environment, ccxt will use them.
- Output Parquet files: data/processed/train.parquet, val.parquet, test.parquet.

## Training (baseline)

- Teacher (NFSDE):
```bash
python train_teacher.py --config configs/nfsde.yaml
```

- Student (DSSM) with distillation:
```bash
python train_student.py --config configs/dssm.yaml
```

### Train router on built dataset

```powershell
# Build dataset first (see section above), then
python scripts/train_router_from_parquet.py --train data/processed/train.parquet --val data/processed/val.parquet --epochs 10 --checkpoint checkpoints/router_best.pt
```

## Notes

- Data connectors are placeholders; connect real sources for Phase 4.
- Router training script and TVF/ICP refinements are pending; see issues.
- CI builds and runs smoke tests; extend with stricter checks for production.

---

## pre-commit hooks

Чтобы ловить ошибки до пуша, установите pre-commit и активируйте хуки:

```bash
pip install pre-commit
pre-commit install
```

Проверить всё дерево:

```bash
pre-commit run --all-files
```

Включённые проверки:
- Validate configs (python tools/validate_config.py --strict)
- yamllint для configs/
- ruff (c автофиксом), black

## Environment (.env)

В корне репозитория добавьте файл `.env` (можно скопировать из `.env.example`) и задайте переменные:

```
BINANCE_API_KEY=...your_key...
BINANCE_API_SECRET=...your_secret...
AURORA_MODE=shadow
```

Ключи не коммитьте. Адаптер Binance автоматически подхватит `.env` при инициализации.

## Unified CLI (auroractl)

Мы мигрируем PowerShell-скрипты на кроссплатформенный Python-CLI `tools/auroractl.py`, который автоматически читает `.env`.

Сопоставление команд:

- scripts/start_api.ps1 → `python tools/auroractl.py start-api [--port 8000 --host 127.0.0.1]`
- scripts/stop_api.ps1 → `python tools/auroractl.py stop-api [--port 8000]`
- scripts/health_check.ps1 → `python tools/auroractl.py health [--port 8000]`
- scripts/run_canary_60.ps1 → `python tools/auroractl.py canary --minutes 60`
- testnet smoke (run_live_testnet + smoke) → `python tools/auroractl.py testnet --minutes 5`
- аудит кошелька → `python tools/auroractl.py wallet-check`
- агрегация метрик → `python tools/auroractl.py metrics --window-sec 3600`
- OPS cooloff/disarm → `python tools/auroractl.py cooloff --sec 120` / `python tools/auroractl.py disarm`

Переключатели среды (только .env): AURORA_MODE, EXCHANGE_TESTNET, DRY_RUN.

Логи ордеров теперь ведутся в три потока JSONL с ротацией:

- logs/orders_success.jsonl
- logs/orders_failed.jsonl
- logs/orders_denied.jsonl

Быстрый старт:

1) Создайте `.env` из `.env.example` и задайте ключи при необходимости. 2) Запустите API: `python tools/auroractl.py start-api`. 3) Прогон канарейки: `python tools/auroractl.py canary --minutes 5`. 4) Сводка: `python tools/auroractl.py metrics --window-sec 600`.
