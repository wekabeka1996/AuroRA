# AURORA v1.2 (Production-Ready Skeleton)

[![canary](https://github.com/${GITHUB_REPOSITORY}/actions/workflows/canary.yml/badge.svg)](https://github.com/${GITHUB_REPOSITORY}/actions/workflows/canary.yml)

This repository implements the AURORA concept (teacher–student, certification, regime-aware) with a working API and training/inference pipelines.

## Quick start

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
