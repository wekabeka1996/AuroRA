# Aurora Configuration System — Production Ready

Aurora використовує багаторівневу систему конфігурацій з підтримкою environments, inheritance та hot reload.

## 📁 Повна структура конфігурацій

```
configs/                          # 🎯 Основна система конфігурацій
├── aurora/                       # Core Aurora API configurations
│   ├── base.yaml                # Базові налаштування (спільні)
│   ├── development.yaml         # Development environment
│   ├── testnet.yaml            # Testnet environment
│   ├── production.yaml         # Production environment
│   └── README.md               # 📖 Детальна документація Aurora API
├── runner/                      # Runner (WiseScalp) configurations  
│   ├── base.yaml               # Базові налаштування runner
│   ├── test_param.yaml         # Тестові параметри
│   └── README.md               # 📖 Детальна документація Runner
├── schema.json                  # JSON схема для валідації
└── README.md                   # 📖 Цей файл

profiles/                        # 🎲 Торгові стратегії та профілі
├── aurora_live_canary.yaml     # Live canary профіль
├── aurora_shadow_best.yaml     # Оптимізований shadow профіль
├── base.yaml                   # Базовий профіль
├── sol_soon_base.yaml         # SOL+SOON мульти-символьна стратегія
├── overlays/                   # Overlay конфігурації
│   └── _active_shadow.yaml    # Активний shadow overlay
└── README.md                   # 📖 Детальна документація профілів

archive/configs_legacy/          # 🗂 Архів застарілих конфігурацій
├── config_old_per_symbol/      # Стара per-symbol система
├── master_config_v1.yaml       # Застарілий master config v1
├── master_config_v2.yaml       # Застарілий master config v2
├── production_ssot.yaml        # Стара SSOT конфігурація
└── README.md                   # 📖 Документація архіву
```

## 🎯 Як вибрати правильну конфігурацію

### Для Aurora API (Core System):
📍 **Місце**: `configs/aurora/`
📖 **Документація**: [configs/aurora/README.md](aurora/README.md)

```bash
# Development режим
export AURORA_MODE=development
python api/service.py

# Testnet режим  
export AURORA_MODE=testnet
python api/service.py

# Production режим
export AURORA_MODE=production
python api/service.py
```

### Для Runner (Trading Bot):
📍 **Місце**: `configs/runner/`
📖 **Документація**: [configs/runner/README.md](runner/README.md)

```bash
# Базова конфігурація runner
python -m skalp_bot.runner.run_live_aurora --config configs/runner/base.yaml

# Тестові параметри
python -m skalp_bot.runner.run_live_aurora --config configs/runner/test_param.yaml
```

### Для торгових стратегій:
📍 **Місце**: `profiles/`
📖 **Документація**: [profiles/README.md](../profiles/README.md)

```bash
# Multi-symbol SOL+SOON стратегія
python -m skalp_bot.runner.run_live_aurora --config profiles/sol_soon_base.yaml

# З overlay для A/B тестування
python -m skalp_bot.runner.run_live_aurora \
  --config profiles/sol_soon_base.yaml \
  --overlay profiles/overlays/_active_shadow.yaml
```

---

## 🔄 Швидкий старт

### 1. Запуск Aurora API:
```bash
# Testnet режим (рекомендовано для початку)
export AURORA_MODE=testnet
python api/service.py
```

### 2. Запуск Runner з SOL/SOON стратегією:
```bash
# Shadow режим (безпечно для тестування)
export DRY_RUN=true
python -m skalp_bot.runner.run_live_aurora --config profiles/sol_soon_base.yaml
```

### 3. Валідація конфігурації:
```bash
# Перевірка API конфігурації
AURORA_MODE=testnet python tools/config_cli.py validate

# Перевірка що все працює
python tools/config_cli.py status
```

## ⚙️ Управління конфігураціями

### Validation та діагностика:
```bash
# Валідація конкретного environment
AURORA_MODE=testnet python tools/config_cli.py validate

# Статус поточної конфігурації  
python tools/config_cli.py status

# Трейсинг завантаження конфігурацій
python tools/config_cli.py trace

# Переключення між environments
python tools/config_cli.py switch --environment production
```

### Environment Variables Override:
```bash
# Override будь-який параметр через env змінні
export AURORA_LATENCY_MS_LIMIT=100
export AURORA_API_TOKEN=your_secure_token
export AURORA_SPREAD_BPS_LIMIT=150

# Перевірка effective конфігурації після override
python tools/config_cli.py status
```

## 📖 Детальна документація

Кожна папка має власну детальну документацію:

### 🎯 Core System (Aurora API):
📖 **[configs/aurora/README.md](aurora/README.md)**
- Environment configurations (dev/test/prod)
- Security settings та токени
- Risk management параметри
- Pretrade gates конфігурація
- Hot reload налаштування

### 🤖 Trading Bot (Runner):
📖 **[configs/runner/README.md](runner/README.md)**
- Runner базові налаштування
- Integration з Aurora API
- Multi-symbol торгівля
- Performance моніторинг
- Testing конфігурації

### 🎲 Trading Strategies (Profiles):
📖 **[profiles/README.md](../profiles/README.md)**
- Multi-symbol профілі
- Parent-child стратегії
- Overlay система для A/B тестів
- Cross-symbol ризик-менеджмент
- Performance аналіз

### 🗂 Legacy Archive:
📖 **[archive/configs_legacy/README.md](../archive/configs_legacy/README.md)**
- Історія розвитку конфігураційної системи
- Проблеми старих підходів
- Міграційні скрипти
- Lessons learned

## 🚨 Важливі зауваження

### ⚠️ Security:
- **Ніколи не коммітьте production токени** в Git
- Використовуйте environment variables для sensitive data
- Регулярно ротуйте API ключі
- Встановлюйте мінімально необхідні permissions

### ⚠️ Production deployment:
- Завжди почніть з `testnet` environment
- Використовуйте `shadow` режим для валідації
- Налаштуйте моніторинг та alerting
- Тестуйте конфігурації в staging середовищі

### ⚠️ Архівні файли:
- **НЕ використовуйте** файли з `archive/configs_legacy/`
- Ці файли збережені виключно для історичних цілей
- Вони можуть містити застарілі та небезпечні налаштування

## 🛠 Troubleshooting

### Типові проблеми:

1. **"Configuration validation failed"**
   ```bash
   # Перевірте синтаксис та валідність
   python tools/config_cli.py validate
   ```

2. **"api_token must be at least 16 characters"**
   ```bash
   # Встановіть токен через env змінну
   export AURORA_API_TOKEN=your_secure_token_here
   ```

3. **"No environment-specific config found"**
   ```bash
   # Перевірте що AURORA_MODE встановлено правильно
   echo $AURORA_MODE
   export AURORA_MODE=testnet
   ```

4. **Конфлікти конфігурацій**
   ```bash
   # Використовуйте трейсинг для діагностики
   python tools/config_cli.py trace
   ```

### Отримання допомоги:
```bash
# CLI довідка
python tools/config_cli.py --help

# Детальна довідка по командах
python tools/config_cli.py validate --help
python tools/config_cli.py trace --help
```

## 🎯 Наступні кроки

1. **Прочитайте детальну документацію** для вашого use case
2. **Налаштуйте environment** відповідно до потреб
3. **Протестуйте в shadow режимі** перед live запуском
4. **Налаштуйте моніторинг** для production використання

**Aurora має production-ready систему конфігурацій - використовуйте її повний потенціал!** 🚀

---

## 🎯 Нова структура конфігурацій

### Активні конфігураційні файли:

```
configs/aurora/          # Production config system
├── base.yaml           # ✅ Базові налаштування (завжди завантажується)
├── testnet.yaml        # ✅ Testnet конфігурація  
├── prod.yaml           # ✅ Production конфігурація
└── development.yaml    # 🔄 Development конфігурація (опційно)

configs/runner/          # Runner-specific configs
├── base.yaml           # ✅ Базові налаштування runner
└── test_param.yaml     # ✅ Тестові параметри

archive/configs_legacy/  # 📦 Архівовані файли
├── master_config_v1.yaml
├── master_config_v2.yaml
├── production_ssot.yaml
├── aurora_config.template.yaml
├── default.toml
├── examples/
└── tests/
```

### ⚙️ Environment Management

Система автоматично визначає environment на основі `AURORA_MODE`:

- `AURORA_MODE=development` → `configs/aurora/development.yaml`
- `AURORA_MODE=testnet` → `configs/aurora/testnet.yaml` 
- `AURORA_MODE=production` → `configs/aurora/prod.yaml`

---

## 🔄 Ієрархія завантаження (Production System)

**Новий ProductionConfigManager** завантажує конфігурацію з чітким пріоритетом:

1. **Environment Variables** (найвищий) — `AURORA_*` overrides
2. **User Specified** — `AURORA_CONFIG=path/to/config.yaml`
3. **Environment Name** — `configs/aurora/{environment}.yaml`
4. **Base Config** (найнижчий) — `configs/aurora/base.yaml`

### 📝 Приклад завантаження для TESTNET:

```bash
Loading sequence:
1. ✓ LOADED  configs/aurora/base.yaml      (priority=DEFAULT)
2. ✓ LOADED  configs/aurora/testnet.yaml   (priority=ENVIRONMENT_NAME)  
3. ✓ LOADED  <environment_variables>       (priority=ENVIRONMENT)
```

---

## 🛠 CLI інструменти

Новий `tools/config_cli.py` надає повний набір інструментів:

```bash
# Статус конфігурації
python tools/config_cli.py status

# Валідація
python tools/config_cli.py validate [environment]

# Перемикання між environments
python tools/config_cli.py switch testnet|production

# Трасування завантаження
python tools/config_cli.py trace

# Показати ієрархію файлів
python tools/config_cli.py hierarchy

# Перевірка конфліктів
python tools/config_cli.py conflicts

# Аудит звіт
python tools/config_cli.py audit [--save]
```

---

## 🚀 Використання

### Запуск API:

```bash
# Testnet
export AURORA_MODE=testnet
export AURORA_API_TOKEN=your_testnet_token
python api/service.py

# Production  
export AURORA_MODE=production
export AURORA_API_TOKEN=your_production_token
python api/service.py
```

### Запуск Runner:

```bash
# З базовою конфігурацією
python -m skalp_bot.runner.run_live_aurora

# З конкретним конфігом
python -m skalp_bot.runner.run_live_aurora --config configs/runner/test_param.yaml
```

---

## 📊 Переваги нової системи

- ✅ **Прозорість**: Повне логування джерел конфігурації
- ✅ **Аудитованість**: Checksums, timestamps, audit trails
- ✅ **Валідація**: Автоматична перевірка обов'язкових секцій
- ✅ **CLI Tools**: Управління через командний рядок
- ✅ **Environment Management**: Чітке розділення dev/test/prod
- ✅ **Backward Compatibility**: Fallback на legacy систему

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
