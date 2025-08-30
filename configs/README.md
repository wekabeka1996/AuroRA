# Конфигурации Aurora — структура, приоритеты и overrides

Этот документ описывает:
- где лежат конфиги сервиса Aurora и раннера (WiseScalp),
- как они резолвятся и подхватываются при старте,
- какие переменные окружения переопределяют YAML,
- как задать SPRT и профиль pre-trade пайплайна,
- как передать конфиг раннеру удобным способом.

Док соответствует текущей реализации в коде: `common/config.py`, `api/service.py`, `tools/run_canary.py`, `tools/auroractl.py`, `core/config_loader.py`.

---

## Структура папки configs

- `configs/aurora/` — конфиги сервиса Aurora (API и pre-trade пайплайн)
  - `base.yaml` — базовый шаблон/профиль
  - `prod.yaml` — рекомендуемый боевой профиль (опционально, может отсутствовать)
  - `testnet.yaml` или `testnet.example.yaml` — пример для тестнета/локалки
- `configs/runner/` — конфиги раннера (скальпер‑бот, отправка ордеров)
  - `base.yaml` — базовый шаблон для раннера
  - `test_param.yaml` — совместимый конфиг для быстрых проверок
- `configs/*.yaml` — легаси‑расположение старых конфигов сервиса (`master_config_v1/v2.yaml`, `aurora_config.template.yaml`)
- `skalp_bot/configs/*.yaml` — легаси‑расположение конфигов раннера

Рекомендация: для сервиса используйте `configs/aurora/*.yaml`, для раннера — `configs/runner/*.yaml`. Легаси файлы поддерживаются для обратной совместимости.

---

## Приоритет загрузки конфигурации сервиса

Загрузка происходит в `api/service.py` через `common/config.py::load_config_precedence` → `apply_env_overrides` по следующему приоритету:

1) Env `AURORA_CONFIG` (путь или bare‑имя без `.yaml`) — самый высокий приоритет
2) Env `AURORA_CONFIG_NAME` (bare‑имя без `.yaml`)
3) Первая существующая из цепочки по умолчанию:
   - `configs/aurora/base.yaml`
   - `configs/aurora/prod.yaml`
   - `configs/aurora/testnet.yaml`
   - `configs/master_config_v2.yaml` (legacy)
   - `configs/master_config_v1.yaml` (legacy)
   - `configs/aurora_config.template.yaml` (legacy)
   - `skalp_bot/configs/default.yaml` (legacy)

Bare‑имя резолвится через `common/config.py::resolve_config_path` в следующем порядке:
- `configs/aurora/<name>.yaml`
- `configs/<name>.yaml`
- `configs/runner/<name>.yaml`
- `skalp_bot/configs/<name>.yaml`

Если по цепочке ничего не найдено — используется пустой словарь (минимальные дефолты из кода).

---

## Env overrides (поверх YAML)

Функция `common/config.py::apply_env_overrides` накладывает переменные окружения на структуру YAML. Поддерживаются ключевые разделы:

- aurora.* (здоровье/холдофф)
  - `AURORA_LATENCY_GUARD_MS` → `aurora.latency_guard_ms` (float)
  - `AURORA_LATENCY_WINDOW_SEC` → `aurora.latency_window_sec` (int)
  - `AURORA_COOLOFF_SEC` → `aurora.cooloff_base_sec` (int)
  - `AURORA_HALT_THRESHOLD_REPEATS` → `aurora.halt_threshold_repeats` (int)

- api/безопасность
  - `AURORA_API_HOST` → `api.host` (str)
  - `AURORA_API_PORT` → `api.port` (int)
  - `OPS_TOKEN` | `AURORA_OPS_TOKEN` → `security.ops_token` (str)

- guards.* (гейты допусков)
  - `AURORA_SPREAD_BPS_LIMIT` → `guards.spread_bps_limit` (float)
  - `AURORA_LATENCY_MS_LIMIT` → `guards.latency_ms_limit` (float)
  - `AURORA_VOL_GUARD_STD_BPS` → `guards.vol_guard_std_bps` (float)
  - `TRAP_GUARD` → `guards.trap_guard_enabled` (bool: 1/true/yes/on)

- risk.* (менеджер риска)
  - `AURORA_PI_MIN_BPS` → `risk.pi_min_bps` (float)
  - `AURORA_MAX_CONCURRENT` → `risk.max_concurrent` (int)
  - `AURORA_SIZE_SCALE` → `risk.size_scale` (float, 0..1)

- slippage.*
  - `AURORA_SLIP_ETA` → `slippage.eta_fraction_of_b` (float)

- pretrade.*
  - `AURORA_ORDER_PROFILE` → `pretrade.order_profile` (str)

- trap.* (окно/параметры ловушки)
  - `AURORA_TRAP_WINDOW_S` → `trap.window_s` (float)
  - `AURORA_TRAP_LEVELS` → `trap.levels` (int)
  - `AURORA_TRAP_Z_THRESHOLD` → `trap.z_threshold` (float)
  - `AURORA_TRAP_CANCEL_PCTL` → `trap.cancel_pctl` (int)

- trading.*
  - `TRADING_MAX_LATENCY_MS` → `trading.max_latency_ms` (int)

Дополнительные рантайм‑переменные (используются напрямую в `api/service.py`):
- `AURORA_SESSION_DIR` — директория сессии логов (`aurora_events.jsonl`, `orders_*.jsonl`)
- `AURORA_ACK_TTL_S`, `AURORA_ACK_SCAN_PERIOD_S` — TTL и период сканера для AckTracker (`observability.ack.*`)

Примечание: булевы значения принимаются как 1/true/yes/on (без регистра, с пробелами допускаются).

---

## SPRT (Sequential Probability Ratio Test)

Раздел YAML: `sprt`

Поддерживаемые поля (см. `common/config.py::SprtConfigModel`):
- `enabled`: bool (по умолчанию true)
- `alpha`, `beta`: float — при наличии обоих `A` и `B` будут автоматически выведены через `thresholds_from_alpha_beta`
- `sigma`: float (по умолчанию 1.0)
- `A`, `B`: float (пороговые значения; если `alpha/beta` заданы, то `A/B` переопределяются ими, если не заданы явные env A/B)
- `max_obs`: int (максимум наблюдений)

Env‑overrides для SPRT:
- `AURORA_SPRT_ENABLED`
- `AURORA_SPRT_ALPHA`
- `AURORA_SPRT_BETA`
- `AURORA_SPRT_SIGMA`
- `AURORA_SPRT_A`
- `AURORA_SPRT_B`
- `AURORA_SPRT_MAX_OBS`

Логика: если заданы `alpha` и `beta` (в YAML или env), `A/B` рассчитываются автоматически. Явные `AURORA_SPRT_A/B` всегда имеют приоритет.

---

## Конфиги раннера (WiseScalp)

Резолвер в `tools/run_canary.py::resolve_runner_config` принимает:
- абсолютный/относительный путь к `.yaml`,
- bare‑имя без расширения (например, `test_param`), которое ищется в:
  1) `configs/runner/<name>.yaml|yml`
  2) `skalp_bot/configs/<name>.yaml|yml`

Пример использования (смысл): передайте флаг `--runner-config test_param` в `one-click/testnet`, и будет найден `configs/runner/test_param.yaml`. Можно также указать полный путь.

По умолчанию (если не передавать флаг) используется легаси путь `skalp_bot/configs/default.yaml`.

---

## Быстрый старт и валидация

- Выбор конфига сервиса через .env:
  - `AURORA_CONFIG` — путь или имя без `.yaml`
  - `AURORA_CONFIG_NAME` — имя без `.yaml` (если `AURORA_CONFIG` не задан)
- Валидация: `tools/auroractl.py config-validate [--name <bare>]`
- One‑click прогон: `tools/auroractl.py one-click --mode testnet --minutes 15 --preflight [--runner-config test_param]`
- Метрики/агрегация по событиям: `tools/auroractl.py metrics --window-sec 3600`

Советы по эксплуатации:
- Логи событий — `logs/aurora_events.jsonl` в каталоге сессии (`AURORA_SESSION_DIR` создаётся автоматически).
- Заказы — в per‑stream файлах `logs/orders_{success,failed,denied}.jsonl` и консолидированно в `orders.jsonl`.
- OPS‑токен читается из `security.ops_token` (YAML) или `OPS_TOKEN`/`AURORA_OPS_TOKEN` (env). Запросы к защищённым эндпоинтам должны содержать заголовок `X-OPS-TOKEN`.

---

## Минимальные примеры YAML (фрагменты)

Aurora (`configs/aurora/base.yaml`):

```yaml
api:
  host: 127.0.0.1
  port: 8000
security:
  ops_token: "<set-in-.env-or-here>"
aurora:
  latency_guard_ms: 30
  latency_window_sec: 60
  cooloff_base_sec: 120
  halt_threshold_repeats: 2
guards:
  spread_bps_limit: 80
  latency_ms_limit: 500
risk:
  pi_min_bps: 5.0
slippage:
  eta_fraction_of_b: 0.25
trap:
  window_s: 2.0
  levels: 5
  z_threshold: 2.2
  cancel_pctl: 90
pretrade:
  order_profile: er_before_slip
sprt:
  enabled: true
  alpha: 0.05
  beta: 0.1
```

Runner (`configs/runner/test_param.yaml`):

```yaml
# пример конфигурации раннера; совместим с skalp_bot/runner
symbol: BTC/USDT
mode: paper
size: 25
# ... другие поля согласно документации раннера
```

---

## FAQ

- Можно ли держать один файл и для сервиса, и для раннера? — Нет, это разные домены и схемы. Поэтому введены папки `configs/aurora` (сервис) и `configs/runner` (раннер).
- Что если у меня ещё `master_config_v2.yaml`? — Поддерживается как легаси. Рекомендуем мигрировать на `configs/aurora/*.yaml`.
- Что приоритетнее: YAML или env? — Env переопределяет YAML через `apply_env_overrides`. Это сделано для быстрых экспериментов и GitOps‑сценариев.
- Как понять, какой конфиг подхватился? — В событиях появится `CONFIG.SWITCHED` c именем/путём; readiness/health возвращают версию.

---

## План дальнейших улучшений (optional)

- Автосборка профилей: `base.yaml` + профиль (prod/testnet) с мерджем, чтобы избежать дублирования.
- Добавить рекомендуемый `configs/aurora/prod.yaml` с безопасными дефолтами.
- Расширить схему валидации для aurora‑конфигов.
