# AURORA — архитектура и контракты

Этот документ описывает ядро сервиса Aurora (FastAPI), pre‑trade пайплайн, наблюдаемость и контракты API, а также роль Governance как финального гейта.

## Обзор компонентов

- Сервис (FastAPI): endpoints `/health`, `/metrics`, `/pretrade/check`, `/posttrade/log`, `/ops/*`.
- PretradePipeline (`core/aurora/pipeline.py`): централизованный порядок гейтов и сбор observability.
- HealthGuard (`aurora/health.py`): p95‑эскалация WARN → COOL_OFF → HALT, OPS‑управление.
- Governance (`aurora/governance.py`): kill‑switch, DQ, риск‑лимиты и микроструктурные условия; финальная проверка `approve()`.
- Observability: `core/aurora_event_logger.py` + Prometheus метрики.
- Order‑логи: `core/order_logger.py` записывает `orders_{success,failed,denied}.jsonl`.

## Pre‑trade пайплайн

Последовательность проверок в `PretradePipeline.decide(...)` (может конфигурироваться):
1. Мгновенная латентность (latency guard)
2. HealthGuard (p95) — может включать cool‑off/halt
3. TRAP (микроструктура; z‑score и конфликты OBI/TFI)
4. Expected Return (IsotonicCalibrator c fallback на Platt)
5. Slippage guard (eta×spread)
6. RiskManager caps/scale (DD/CVaR/лимиты)
7. Необязательный SPRT
8. Spread guard
9. Governance.approve(...) — финальное решение allow/reasons

Endpoint `/pretrade/check` делегирует решение пайплайну, эмитит событие `POLICY.DECISION`, при блокировке спредом — `SPREAD_GUARD_TRIP`, инкрементирует счётчики и логирует `orders_denied.jsonl` при отказе.

## Governance и Health

- HealthGuard: следит за p95 задержки, эскалирует состояние и может блокировать торговлю на время (`cooloff`). OPS: `/ops/cooloff/{sec}`, `/ops/reset`, `/aurora/{arm|disarm}`.
- Governance: контролирует kill‑switch (шторм отказов), флаги качества данных, риск‑гейты (дневная просадка, CVaR), микроструктурные условия (спред/латентность/волатильность), позиционные лимиты. Метод `approve(intent, risk_state)` может переопределить `allow/reason` и дополнить `reasons`.

## Контракты API

- Входные/выходные модели REST определены в `api/models.py` (Pydantic v2). Основные: `PretradeCheckRequest`, `PretradeCheckResponse` и модели post‑trade.
- Downstream‑схемы (для файлов/шины): `core/schemas.py` — `DecisionFinal`, `Order{Success,Failed,Denied}`.
- Разделение уровней: REST‑контракты ≠ внутренние схемы. Для маппинга используем явно `core/converters.py`:
	- `api_order_to_denied_schema(...)` → `OrderDenied`
	- `posttrade_to_success_schema(...)` → `OrderSuccess`
	- `posttrade_to_failed_schema(...)` → `OrderFailed`

## Наблюдаемость и метрики

- События: `core/aurora_event_logger.py` пишет `aurora_events.jsonl` в каталоге сессии. Схема кода событий — `observability/codes.py`.
- Метрики Prometheus: `/metrics`. Включают latency histogram, counters (events, orders_{success,failed,denied}), gauges при необходимости.
- Разделённые order‑логи: `logs/orders_success.jsonl`, `logs/orders_failed.jsonl`, `logs/orders_denied.jsonl` (с файловыми блокировками).

## TRAP и калибровка

- TRAP: `core/scalper/trap.py` — окно `TrapWindow`, расчёт `trap_z`, флаг конфликта OBI/TFI, пороги `z_threshold`. Параметр `cancel_pctl` — используется на уровне гейта как условие фильтра, документирован в конфиге.
- Expected Return: `core/scalper/calibrator.py` — приоритетно изотоническая калибровка; при отсутствии — fallback на Platt Scaling. `e_pi_bps(p,R,fee_bps)` формирует ожидаемую доходность в б.п.

## Конфигурация

- Принцип: ENV > YAML > дефолты. Консолидированный загрузчик в `common/config.py`.
- Ключевые ENV: `AURORA_LMAX_MS`, `AURORA_TRAP_Z_THRESHOLD`, `AURORA_TRAP_CANCEL_PCTL`, `AURORA_PI_MIN_BPS`, `AURORA_SLIP_ETA`, `AURORA_SPREAD_BPS_LIMIT`, `AURORA_SPRT_ENABLED`, `OPS_TOKEN`.

## Aurora API Lite (dev only)

- `aurora_api_lite.py` — облегчённый сервер для интеграционных сценариев. Асинхронные задержки (`asyncio.sleep`), observability поля согласованы с основным сервисом. Не использовать в проде.

---

Примечание: этот документ синхронизирован с реализацией PretradePipeline и Governance по состоянию на 2025‑08‑28.
