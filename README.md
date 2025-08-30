AURORA — Risk Gate API and Runner Integration

Коротко
- Aurora (FastAPI) — централізований pre‑trade гейт, health/ops, метрики Prometheus, події JSONL.
- WiseScalp (runner) — генерує альфа‑сигнали і ПЕРЕД кожним ордером звертається до Aurora `/pretrade/check`.
- Логи/події: структуровані JSONL у каталозі сесії `logs/YYYYMMDD-hhmmss/`.

Структура проєкту
- api/ — FastAPI сервіс: lifespan, ендпоінти, метрики.
- core/
  - aurora/ — доменна логіка: гейти (`pretrade.py`), health/governance, подієвий логер.
  - scalper/ — сигнали/калібратори: isotonic+Platt fallback, TRAP, SPRT, ICP.
  - … інші утиліти: `order_logger.py`, `ack_tracker.py`, `reward_manager.py`.
- common/ — конфіг і крос‑утиліти (єдиний loader, адаптер EventEmitter → AuroraEventLogger).
- observability/ — коди подій і JSON‑схеми (див. `observability/README.md`).
- risk/ — RiskManager (щоденні ліміти, scale, concurrent caps).
- configs/ — YAML‑конфіги (ENV має пріоритет над YAML).
- docs/ — документація (паспорт, AURORA.md, план рефакторингу).
- skalp_bot/ — інтеграції/runner‑клієнт (AuroraGate HTTP клієнт).
- tests/ — юніт/інтеграційні тести.
- tools/ — допоміжні утиліти (ctl, архівація тощо).

Контракт pre‑trade
- Запит: `PretradeCheckRequest` складається з `account`, `order`, `market` (строго типізовані моделі у `api/models.py`).
- Основний пайплайн (порядок може бути сконфігурований):
  1) latency guard (миттєвий поріг) →
  2) HealthGuard (p95 ескалації) →
  3) TRAP guard →
  4) expected return (isotonic) →
  5) slippage guard →
  6) RiskManager caps/scale →
  7) optional SPRT →
  8) spread guard.
- Відповідь: `allow`, `max_qty`, `risk_scale`, `cooldown_ms`, `reason`, `observability`.

Observability
- Події: `core/aurora_event_logger.py` пише у `aurora_events.jsonl` (у сесії `AURORA_SESSION_DIR`).
- Канонічні поля запису: `ts_ns`, `run_id`, `event_code`, `details`, інші — опційні (`symbol`, `cid`, `oid`, `side`, `qty`, ...).
- Схема: див. `observability/aurora_event.schema.json` (файл `observability/schema.json` лишається як legacy‑схема для старого еммітера; не використовується новим логгером).
- Метрики Prometheus: `/metrics` (латентність, лічильники подій/ордерів, OPS‑метрики).

PretradePipeline
- Центральна логіка тепер інкапсульована у `core/aurora/pipeline.py`. Сервісний ендпоінт `/pretrade/check` делегує прийняття рішення пайплайну й повертає `(allow, reason, observability, risk_scale)`.
- Сервіс додатково: персистить створений `trap_window` у `app.state`, емить `POLICY_DECISION`, при блокуванні спредом емить `SPREAD_GUARD_TRIP`, інкрементує `aurora_orders_denied_total` та пише у `orders_denied.jsonl`.

Governance & Health
- `aurora/governance.py`: kill‑switch (reject storms), дані якості та системні ліміти.
- `aurora/health.py`: HealthGuard (p95) з ескалацією WARN → COOL_OFF → HALT. OPS: `/ops/cooloff/{sec}`, `/ops/reset`, `/aurora/{arm|disarm}`.

ENV → YAML пріоритети (приклади)
- Latency: `AURORA_LMAX_MS`
- TRAP: `AURORA_TRAP_Z_THRESHOLD`, `AURORA_TRAP_CANCEL_PCTL`, `TRAP_GUARD`
- ER: `AURORA_PI_MIN_BPS`
- Slippage: `AURORA_SLIP_ETA`
- Spread: `AURORA_SPREAD_BPS_LIMIT` (або `AURORA_SPREAD_MAX_BPS`)
- SPRT: `AURORA_SPRT_ENABLED`, `AURORA_SPRT_TIMEOUT_MS`
- ICP (опціонально): `AURORA_ICP_OBS=1`
- OPS: `OPS_TOKEN` (alias `AURORA_OPS_TOKEN` підтримується, але емить WARN)

Приклад `.env`:
```
AURORA_CONFIG=configs/v4_min.yaml
AURORA_LMAX_MS=30
AURORA_TRAP_Z_THRESHOLD=1.64
AURORA_TRAP_CANCEL_PCTL=90
AURORA_PI_MIN_BPS=2.0
AURORA_SLIP_ETA=0.3
AURORA_SPREAD_BPS_LIMIT=80
AURORA_SPRT_ENABLED=1
OPS_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

Схеми: API vs Downstream
- REST‑контракти у `api/models.py` (вхід/вихід FastAPI).
- Downstream‑події/ордери у `core/schemas.py` (для файлів/шини). Не змішуйте рівні; за потреби використовуйте явні конвертери.
 - Конвертери: `core/converters.py` надає явні мапінги між REST‑моделями та downstream‑схемами:
   - `api_order_to_denied_schema(...)` → `OrderDenied`
   - `posttrade_to_success_schema(...)` → `OrderSuccess`
   - `posttrade_to_failed_schema(...)` → `OrderFailed`
   Сервіс при логуванні order‑подій за можливості використовує ці конвертери для структурованих записів.

Aurora API Lite (dev‑only)
- `aurora_api_lite.py` — спрощений варіант для демо/інтеграційних сценаріїв. Не для продакшена; контракт наближений до `/pretrade/check`, але можливі службові поля (`cooldown_ms`, `hard_gate`).
 - Уточнення: реалізація асинхронізована (`asyncio.sleep`), а поля спостережуваності узгоджені з основним сервісом.

Config & ENV
- Пріоритет: ENV > YAML > дефолти. Консолідований loader у `common/config.py` (перехід від дублікатів).
- Ключові обмеження за замовчуванням: `latency_ms_limit=500`, `spread_bps_limit=80`, `daily_dd_limit_pct=10`, `cvar_alpha=0.1`.

Як запускати локально
- API: `python api/service.py` (або через VS Code task). Ендпоінти: `/health`, `/metrics`, `/pretrade/check`, `/posttrade/log`.
- Runner: налаштуйте `.env` (див. `skalp_bot/README*.md`) і запускайте `skalp_bot.runner.run_live_aurora`.

Тести
- У VS Code задано готові задачі для таргетних прогонів (див. Tasks). Рекомендовано починати з інтеграційних pre‑trade тестів.
