# Aurora Configuration Documentation

Цей документ описує всі конфігураційні файли системи Aurora та їх призначення.

## 📁 Структура конфігурацій

```
configs/
├── aurora/           # Core Aurora API configurations
│   ├── base.yaml     # Base configuration (shared)
│   ├── development.yaml   # Development environment
│   ├── testnet.yaml      # Testnet environment  
│   ├── production.yaml   # Production environment
│   └── README.md         # This file
├── runner/           # Runner (WiseScalp) configurations
│   ├── base.yaml     # Base runner config
│   ├── test_param.yaml   # Test parameters
│   └── README.md     # Runner config documentation
├── schema.json       # JSON schema for validation
└── README.md         # Main configuration documentation
```

## 🎯 Environment-based Configuration Loading

Aurora використовує ієрархічну систему завантаження конфігурацій:

### Пріоритети (від найвищого до найнижчого):
1. **Environment Variables** (найвищий пріоритет)
2. **Environment-specific YAML** (`development.yaml`, `testnet.yaml`, `production.yaml`)
3. **Base YAML** (`base.yaml`)

### Переключення між environments:
```bash
# Development mode
export AURORA_MODE=development
python api/service.py

# Testnet mode  
export AURORA_MODE=testnet
python api/service.py

# Production mode
export AURORA_MODE=production
python api/service.py
```

## 📋 Опис конфігураційних файлів

### `base.yaml` - Базова конфігурація
**Призначення**: Загальні налаштування, які використовуються у всіх environments.

**Основні секції**:
- `api`: Налаштування FastAPI сервера
- `aurora`: Core Aurora параметри (latency, cooloff)  
- `guards`: Претрейд-гейти та обмеження
- `risk`: Управління ризиками
- `slippage`: Параметри слипажу
- `trap`: Антитрап система
- `pretrade`: Конфігурація претрейд pipeline
- `sprt`: Sequential Probability Ratio Test

**Коли змінювати**: Тільки при глобальних змінах логіки, що впливають на всі environments.

### `development.yaml` - Development Environment
**Призначення**: Розслаблені налаштування для локальної розробки.

**Ключові особливості**:
- Великі tolerance для latency та spread
- Відключені суворі гейти (trap_guard_enabled: false)
- Малий розмір позицій (size_scale: 0.1)
- Короткі cooloff періоди
- Відключений SPRT для швидкого тестування

**Коли використовувати**: Локальна розробка, дебагінг, швидкі тести.

### `testnet.yaml` - Testnet Environment  
**Призначення**: Помірні налаштування для тестування на testnet.

**Ключові особливості**:
- Помірні обмеження (spread_bps_limit: 120)
- Включені гейти для реалістичного тестування
- Середні розміри позицій
- Testnet API токени
- Включений trap guard

**Коли використовувати**: Інтеграційне тестування, валідація стратегій.

### `production.yaml` - Production Environment
**Призначення**: Суворі налаштування для живої торгівлі.

**Ключові особливості**:
- Мінімальні tolerance (spread_bps_limit: 80)
- Всі гейти включені та налаштовані консервативно
- Малі розміри позицій (size_scale: 0.2)
- Суворі ризик-контролі (dd_day_pct: 8.0)
- Production API токени (потребують заміни)

**⚠️ ВАЖЛИВО**: Перед production deployment замініть placeholder токени!

## 🔐 Security Configuration

Всі environments містять токени безпеки:

```yaml
security:
  ops_token: "операційний токен для /ops endpoints"
  api_token: "API токен для автентифікації"
```

### Production Security:
- Токени повинні бути мінімум 16 символів
- Рекомендується використовувати environment variables для production
- Розгляньте використання Azure KeyVault або подібних рішень

## 🧪 Валідація конфігурацій

Перевірка конфігурації перед запуском:

```bash
# Валідація specific environment
AURORA_MODE=testnet python tools/config_cli.py validate

# Перегляд effective configuration
AURORA_MODE=testnet python tools/config_cli.py status

# Трейсинг завантаження конфігурацій
python tools/config_cli.py trace
```

## 🔄 Модифікація конфігурацій

### Environment Variables Override
Будь-який параметр можна перевизначити через змінні середовища:

```bash
# Override latency limit
export AURORA_LATENCY_MS_LIMIT=100

# Override API token
export AURORA_API_TOKEN=your_secure_token_here

# Override spread limit  
export AURORA_SPREAD_BPS_LIMIT=150
```

### Hot Reload
Деякі параметри підтримують hot reload без перезапуску:
- `risk.cvar.limit`
- `risk.cvar.alpha`
- `execution.sla.max_latency_ms`
- `governance.*`

## 📚 Додаткова документація

- `configs/runner/README.md` - Документація конфігурацій runner
- `configs/schema.json` - JSON схема для валідації
- `.github/copilot-instructions.md` - Інструкції для розробки

## 🚨 Troubleshooting

### Типові проблеми:

1. **"api_token must be at least 16 characters"**
   - Встановіть `AURORA_API_TOKEN` або змініть токен в YAML

2. **"Configuration validation failed"**  
   - Перевірте синтаксис YAML
   - Запустіть `python tools/config_cli.py validate`

3. **"No environment-specific config found"**
   - Перевірте що `AURORA_MODE` встановлено правильно
   - Перевірте що відповідний `.yaml` файл існує

4. **Конфлікти конфігурацій**
   - Використовуйте `python tools/config_cli.py trace` для діагностики
   - Перевірте пріоритети завантаження