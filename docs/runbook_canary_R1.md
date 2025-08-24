# GO/NO-GO (R1) — 60‑минутная канарейка

Этот ранбук описывает быструю процедуру оценки готовности к выпуску на основе артефактов наблюдаемости и summary‑gate.

## Предпосылки
- API Aurora поднят (локально или в Docker); события пишутся в `logs/events.jsonl`.
- Скрипты и зависимости установлены: `pip install -r requirements.txt -r requirements-dev.txt`.
- Фиче‑флаг порядка гейтов: `PRETRADE_ORDER_PROFILE` (по умолчанию `er_before_slip`). Допустимые значения:
  - `er_before_slip` (рекомендуется)
  - `slip_before_er`

## Бизнес‑правила summary‑gate
Summary‑gate завершает процесс с кодом 1 при нарушении любого из правил:
- slip_mae_ratio > 0.30 (на основании расчёта MAE/mean(model_bps))
- ≥2 одинаковых событий RISK.DENY за последние 5 минут
- ≥2 событий HEALTH.LATENCY_* за последние 5 минут
- В строгом режиме: отсутствуют сигналы, указывающие на наличие прибыльных возможностей (грубая эвристика по Reasons)

Параметры порогов можно переопределить флагами CLI: `--slip-threshold`, `--risk-threshold`, `--latency-threshold`, `--window-sec`.

## Процедура (локально)
1) Собрать сводку (создаст артефакты в `reports/`):
   - PowerShell
     - `python tools/canary_summary.py --events logs/events.jsonl --out-ts reports/latency_p95_timeseries.csv --out-flow reports/escalations_flow.md --out-md reports/canary_60min_summary.md`
   - Bash
     - `python tools/canary_summary.py --events logs/events.jsonl --out-ts reports/latency_p95_timeseries.csv --out-flow reports/escalations_flow.md --out-md reports/canary_60min_summary.md`

2) Запустить summary‑gate (строгий режим):
   - PowerShell
     - `python tools/summary_gate.py --summary reports/canary_60min_summary.md --events logs/events.jsonl --strict`
   - Bash
     - `python tools/summary_gate.py --summary reports/canary_60min_summary.md --events logs/events.jsonl --strict`

Ожидаемые артефакты:
- `reports/latency_p95_timeseries.csv` — временной ряд p95 задержек
- `reports/escalations_flow.md` — поток эскалаций HEALTH/AURORA
- `reports/canary_60min_summary.md` — сводная таблица Reasons/Risk/Slippage

## Интерпретация
- `SUMMARY GATE: OK` → GO (при соблюдении дополнительных продуктовых критериев)
- `SUMMARY GATE: FAIL` → NO‑GO. Причины будут перечислены построчно (например, `risk_deny_repeated:RISK.DENY.DD_DAYx3`).

## Автокулдаун в harness
Канарейный harness может автоматически отправить `POST /ops/cooloff` один раз при первом нарушении Risk/Latency до «жёсткой» остановки. Управление флагом: `--no-autocooloff`.

## Быстрый QA порядка гейтов
- PowerShell: `scripts/qa_pretrade_order.ps1`
- Bash: `scripts/qa_pretrade_order.sh`

## Валидация конфигов
Запустить строгую проверку всех YAML:
- PowerShell/Bash: `python tools/validate_config.py --strict configs/*.yaml`

## Частые вопросы
- Как узнать текущий профиль порядка?
  - `GET /health` возвращает блок `version.order_profile`.
- Как сменить в рантайме OPS‑токен?
  - `POST /ops/rotate_token` (требуется текущий токен в заголовке авторизации).
