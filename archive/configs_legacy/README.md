# Aurora Legacy Configurations Archive

Цей архів містить застарілі конфігураційні файли Aurora, збережені для історичних цілей та можливого аналізу.

## 📁 Структура архіву

```
archive/configs_legacy/
├── config_old_per_symbol/       # Стара per-symbol система
│   ├── live/
│   │   ├── SOL/config.yaml     # SOLUSDT live конфіг
│   │   └── SOON/config.yaml    # SOONUSDT live конфіг
│   └── testnet/
│       ├── BTC/config.yaml     # BTCUSDT testnet конфіг
│       └── ETH/config.yaml     # ETHUSDT testnet конфіг
├── master_config_v1.yaml        # Перша версія master конфігу
├── master_config_v2.yaml        # Друга версія master конфігу
├── production_ssot.yaml         # Стара SSOT конфігурація
├── aurora_config.template.yaml  # Застарілий template
├── default.toml                 # TOML формат (не використовується)
├── examples/                    # Папка з прикладами
├── tests/                       # Тестові конфігурації
└── README.md                    # Цей файл
```

## ⚠️ ВАЖЛИВО: Ці файли застарілі!

**Всі файли в цьому архіві НЕ ВИКОРИСТОВУЮТЬСЯ** в поточній системі Aurora і збережені виключно для:

1. **Історичного аналізу** - розуміння еволюції конфігураційної системи
2. **Міграційних цілей** - якщо потрібно відновити старі налаштування
3. **Audit trail** - для compliance та debugging історичних issues
4. **Reference** - порівняння зі старими підходами

## 🚫 Чому ці конфігурації були архівовані

### Проблеми зі старою системою:

#### 1. Per-Symbol конфлікти (`config_old_per_symbol/`)
- **Проблема**: Кожен символ мав окремий файл конфігурації
- **Конфлікт**: Неможливо було керувати multi-symbol стратегіями  
- **Рішення**: Заміна на `profiles/` систему з multi-symbol підтримкою

#### 2. Master Config дублювання (`master_config_v1.yaml`, `master_config_v2.yaml`)
- **Проблема**: Множинні версії master конфігурації
- **Конфлікт**: Неясність який файл має пріоритет
- **Рішення**: Єдина environment-based система (`configs/aurora/`)

#### 3. SSOT конфлікти (`production_ssot.yaml`)
- **Проблема**: Single Source of Truth файл конфліктував з іншими
- **Конфлікт**: Unclear precedence та inheritance
- **Рішення**: Чітка ієрархія через ProductionConfigManager

#### 4. Format inconsistency (`default.toml`)
- **Проблема**: Змішування YAML та TOML форматів
- **Конфлікт**: Різні парсери та validation rules
- **Рішення**: Стандартизація на YAML

## 📊 Аналіз архівних конфігурацій

### `config_old_per_symbol/` - Стара per-symbol система

#### Структура старих per-symbol файлів:
```yaml
# Приклад: config_old_per_symbol/live/SOL/config.yaml
symbol: SOLUSDT
execution:
  broker: shadow
  sla:
    max_latency_ms: 250
sizing:
  kelly:
    clip_min: 0.0
    clip_max: 0.005
  limits:
    min_notional_usd: 10
    max_notional_usd: 100
```

#### Проблеми підходу:
- ❌ **Дублювання**: Однакові налаштування в кожному файлі
- ❌ **Складність управління**: Зміна глобального параметра потребувала оновлення всіх файлів
- ❌ **Відсутність кореляції**: Неможливо було налаштувати cross-symbol стратегії
- ❌ **Версіонування**: Важко відстежувати зміни в десятках файлів

#### Сучасна альтернатива:
```yaml
# profiles/sol_soon_base.yaml - новий підхід
universe:
  symbols: [SOLUSDT, SOONUSDT]    # Multi-symbol у одному файлі

parent_gate:                      # Cross-symbol логіка
  enabled: true
  parent: SOLUSDT
  child: SOONUSDT
```

### `master_config_v1.yaml` vs `master_config_v2.yaml`

#### Еволюція master конфігурації:

**v1** (Простий підхід):
```yaml
# master_config_v1.yaml
api:
  host: 127.0.0.1
  port: 8000
symbols: [BTCUSDT]
risk:
  limit: 0.02
```

**v2** (Спроба розширення):
```yaml
# master_config_v2.yaml
api:
  host: 127.0.0.1
  port: 8000
  auth:
    token: "placeholder"
symbols: [BTCUSDT, ETHUSDT]
risk:
  cvar:
    limit: 0.02
    alpha: 0.95
execution:
  sla:
    max_latency_ms: 25
```

#### Проблеми master підходу:
- ❌ **Monolithic**: Все в одному файлі
- ❌ **Environment mixing**: Dev/test/prod параметри разом
- ❌ **Неможливість override**: Складно змінити частину конфігу
- ❌ **Версіонні конфлікти**: v1 vs v2 неясність

#### Сучасне рішення:
```
configs/aurora/
├── base.yaml         # Спільні налаштування  
├── development.yaml  # Dev-specific
├── testnet.yaml     # Test-specific
└── production.yaml  # Prod-specific
```

### `production_ssot.yaml` - Проблеми SSOT підходу

#### Ідея SSOT:
```yaml
# production_ssot.yaml
# "Single Source of Truth" для всіх налаштувань
api: { ... }
risk: { ... }
execution: { ... }
sizing: { ... }
# ... всі можливі параметри
```

#### Чому не спрацювало:
- ❌ **Too comprehensive**: Занадто багато в одному файлі
- ❌ **Environment agnostic**: Не враховує різниці dev/test/prod
- ❌ **Inheritance complexity**: Складна логіка успадкування
- ❌ **Validation issues**: Важко валідувати величезний файл

#### Сучасний підхід:
- ✅ **Environment separation**: Різні файли для різних environments
- ✅ **Layered inheritance**: base.yaml + environment-specific
- ✅ **Clear validation**: Кожен файл має фокусовану відповідальність

## 🔄 Міграція зі старих конфігурацій

Якщо потрібно відновити налаштування зі старих файлів:

### 1. Per-Symbol → Profiles:
```bash
# Аналіз старих налаштувань
cat archive/configs_legacy/config_old_per_symbol/live/SOL/config.yaml

# Створення нового профілю
cp profiles/base.yaml profiles/my_migrated_sol.yaml
# Редагувати my_migrated_sol.yaml з урахуванням старих параметрів
```

### 2. Master Config → Environment Config:
```bash
# Аналіз старого master config
cat archive/configs_legacy/master_config_v2.yaml

# Додавання параметрів в environment config
# Редагувати configs/aurora/testnet.yaml або production.yaml
```

### 3. Automated Migration Script:
```python
#!/usr/bin/env python3
"""
Приклад скрипту для міграції старих конфігурацій
"""
import yaml
from pathlib import Path

def migrate_per_symbol_to_profile(old_config_dir, new_profile_path):
    """Migrate old per-symbol configs to new profile format"""
    symbols = []
    base_config = {}
    
    # Зібрати всі символи та спільні налаштування
    for symbol_dir in Path(old_config_dir).iterdir():
        if symbol_dir.is_dir():
            config_file = symbol_dir / "config.yaml"
            if config_file.exists():
                with open(config_file) as f:
                    config = yaml.safe_load(f)
                    symbols.append(config.get('symbol'))
                    # Зібрати спільні налаштування
                    for key in ['execution', 'sizing', 'reward']:
                        if key in config:
                            base_config[key] = config[key]
    
    # Створити новий профіль
    new_profile = {
        'universe': {'symbols': symbols},
        **base_config
    }
    
    with open(new_profile_path, 'w') as f:
        yaml.dump(new_profile, f, default_flow_style=False)
    
    print(f"Migrated {len(symbols)} symbols to {new_profile_path}")

# Використання:
# migrate_per_symbol_to_profile(
#     "archive/configs_legacy/config_old_per_symbol/live",
#     "profiles/migrated_live.yaml"
# )
```

## 📚 Lessons Learned

### Чому нова система краща:

#### 1. **Clear Separation of Concerns**:
- API конфігурації (`configs/aurora/`) vs торгові стратегії (`profiles/`)
- Environment separation (dev/test/prod)
- Фокусовані файли замість monolithic

#### 2. **Maintainable Inheritance**:
- Чітка ієрархія: base → environment → overrides
- Environment variables мають найвищий пріоритет
- Overlay система для temporary змін

#### 3. **Production Ready**:
- Schema validation
- Hot reload підтримка  
- Audit trail та tracing
- Security best practices

#### 4. **Developer Friendly**:
- IDE support (YAML + schema)
- Clear error messages
- Validation tools (`config_cli.py`)
- Comprehensive documentation

## 🚨 Не використовуйте архівні файли!

**Ці файли збережені виключно для історичних цілей.**

### Для нових проектів використовуйте:
- ✅ `configs/aurora/` - для API конфігурацій
- ✅ `profiles/` - для торгових стратегій  
- ✅ `tools/config_cli.py` - для управління конфігураціями

### При виникненні питань:
1. Перевірте сучасну документацію
2. Використовуйте `python tools/config_cli.py --help`
3. Відверніться до `configs/README.md`
4. Зверніться до команди розробки

**Архівні файли можуть містити застарілі та потенційно небезпечні налаштування!**