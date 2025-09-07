# Aurora Profiles Documentation

Цей документ описує систему профілів Aurora - спрощений підхід до конфігурації multi-symbol торгівлі.

## 📁 Структура профілів

```
profiles/
├── aurora_live_canary.yaml      # Live canary профіль
├── aurora_shadow_best.yaml      # Найкращий shadow профіль  
├── base.yaml                    # Базовий профіль
├── sol_soon_base.yaml          # SOL+SOON мульти-символьний профіль
├── overlays/                    # Overlay конфігурації
│   └── _active_shadow.yaml     # Активний shadow overlay
└── README.md                    # Цей файл
```

## 🎯 Концепція профілів

Профілі - це **спрощена альтернатива** повним конфігураціям Aurora, призначена для:

- **Multi-symbol trading**: Торгівля кількома символами одночасно
- **Quick setup**: Швидке налаштування для конкретних стратегій  
- **Strategy templates**: Готові шаблони для різних підходів
- **A/B testing**: Порівняння різних налаштувань

### Відмінність від основних конфігурацій:
- `configs/aurora/` - Повні системні конфігурації (API, risk management, всі гейти)
- `profiles/` - Фокусовані налаштування для конкретних торгових стратегій

## 📋 Опис профілів

### `base.yaml` - Базовий профіль

**Призначення**: Мінімальний шаблон для створення нових профілів.

**Основні секції**:
```yaml
universe:
  symbols: [BTCUSDT, ETHUSDT]    # Базові символи

sizing:
  limits:
    max_notional_usd: 500        # Консервативний розмір
  kelly_scaler: 0.1              # Помірний ризик

execution:
  broker: shadow                 # Безпечний shadow режим
  sla:
    max_latency_ms: 300          # Стандартна латентність

reward:
  take_profit_bps: 15            # Консервативний TP
  stop_loss_bps: 30              # Консервативний SL
```

**Коли використовувати**: Як початкову точку для нових стратегій.

### `sol_soon_base.yaml` - SOL+SOON стратегія

**Призначення**: Спеціалізований профіль для торгівлі парою SOLUSDT/SOONUSDT.

**Ключові особливості**:
```yaml
universe:
  symbols: [SOLUSDT, SOONUSDT]   # Фокус на SOL екосистемі

sizing:
  limits:
    max_notional_usd: 100        # Малі позиції для volatility
  kelly_scaler: 0.08             # Агресивніший ризик

parent_gate:                     # Спеціальний parent-child гейт
  enabled: true
  parent: SOLUSDT                # SOLUSDT як головний індикатор
  child: SOONUSDT                # SOONUSDT слідує за SOLUSDT
  z_threshold: 0.75              # Поріг кореляції
  align_sign: true               # Однакові напрямки
```

**Стратегічна логіка**:
- SOLUSDT як "parent" індикатор ринку SOL
- SOONUSDT як "child" що часто слідує за SOL рухами
- Parent-child гейт запобігає трейдам проти кореляції

**Коли використовувати**: Торгівля SOL екосистемою з focus на correlation arbitrage.

### `aurora_shadow_best.yaml` - Оптимізований shadow профіль

**Призначення**: Найкращі налаштування для shadow trading (DRY_RUN режим).

**Оптимізації**:
- Налаштування основані на backtesting результатах
- Оптимальні threshold для різних ринкових умов
- Збалансований ризик-профіль для тривалої роботи

**Коли використовувати**: Production shadow trading для збору статистики без ризику.

### `aurora_live_canary.yaml` - Live canary профіль

**Призначення**: Обережний профіль для перших live запусків.

**Характеристики "canary"**:
- Мінімальні розміри позицій
- Суворі ризик-контролі  
- Короткі exposure періоди
- Консервативні threshold

**Коли використовувати**: Перший перехід з shadow на live trading.

## 🔄 Overlay система

### `overlays/_active_shadow.yaml` - Активний overlay

**Призначення**: Динамічні override для існуючих профілів без зміни основних файлів.

**Приклад використання**:
```yaml
# Тимчасово змінити розміри позицій
sizing:
  limits:
    max_notional_usd: 50  # Override значення з базового профілю

# Тимчасово змінити ризик-параметри  
reward:
  stop_loss_bps: 25       # Тугіший stop loss
```

**Переваги overlay**:
- Швидкі A/B тести без зміни основних профілів
- Тимчасові налаштування для особливих ринкових умов
- Можливість швидкого rollback

## 🚀 Використання профілів

### Запуск з профілем:
```bash
# Використання конкретного профілю
python -m skalp_bot.runner.run_live_aurora --config profiles/sol_soon_base.yaml

# З overlay
python -m skalp_bot.runner.run_live_aurora \
  --config profiles/sol_soon_base.yaml \
  --overlay profiles/overlays/_active_shadow.yaml
```

### Через auroractl:
```bash
# One-click запуск з профілем
python tools/auroractl.py one-click \
  --profile sol_soon_base \
  --mode live \
  --minutes 60
```

## 🎛️ Environment integration

Профілі працюють разом з Aurora environment конфігураціями:

### Workflow:
1. **Aurora API** завантажує environment config (`testnet.yaml`, `production.yaml`)
2. **Runner** завантажує профіль (`sol_soon_base.yaml`)  
3. **Overlay** застосовує додаткові override
4. **Environment variables** мають найвищий пріоритет

### Приклад комбінації:
```bash
# Aurora API в testnet режимі + SOL/SOON профіль + shadow overlay
export AURORA_MODE=testnet
export DRY_RUN=true

python api/service.py &  # Aurora API (testnet config)
python -m skalp_bot.runner.run_live_aurora \
  --config profiles/sol_soon_base.yaml \
  --overlay profiles/overlays/_active_shadow.yaml
```

## 📊 Multi-Symbol координація

### Parent-Child стратегії:
```yaml
parent_gate:
  enabled: true
  parent: BTCUSDT           # Головний символ
  child: ETHUSDT           # Залежний символ
  lookback_s: 120          # Вікно кореляції
  z_threshold: 1.0         # Поріг кореляції
  align_sign: true         # Однакові напрямки сигналів
  max_spread_bps: 50       # Максимальний spread між символами
  cooloff_s: 30            # Cooloff після спрацьовування
```

### Cross-Symbol ризик-менеджмент:
```yaml
risk:
  cross_symbol:
    max_total_exposure_usd: 500    # Загальна експозиція по всіх символах
    max_correlated_pairs: 2        # Максимум корельованих позицій
    correlation_threshold: 0.7     # Поріг кореляції
```

## 🔧 Створення власного профілю

### Шаблон нового профілю:
```yaml
# my_strategy.yaml
universe:
  symbols: [YOUR_SYMBOL1, YOUR_SYMBOL2]

sizing:
  limits:
    min_notional_usd: 10
    max_notional_usd: 200
  kelly_scaler: 0.05              # Початково консервативно

execution:
  broker: shadow                  # Завжди почніть з shadow
  router:
    spread_limit_bps: 20
  sla:
    max_latency_ms: 250

reward:
  ttl_minutes: 15
  take_profit_bps: 12
  stop_loss_bps: 25
  expected_net_reward_threshold_bps: 0.0

# Опціонально: спеціальні гейти
parent_gate:
  enabled: false

# Опціонально: custom risk параметри
risk:
  custom_param: value
```

### Best practices для профілів:
1. **Почніть з shadow режиму** для валідації
2. **Малі розміри позицій** спочатку
3. **Консервативні TP/SL** до оптимізації
4. **Тестуйте на історичних даних** перед live
5. **Використовуйте overlay** для швидких налаштувань

## 🧪 Testing профілів

### Backtesting з профілем:
```bash
# Історичне тестування профілю
python tools/backtest.py \
  --config profiles/sol_soon_base.yaml \
  --start-date 2024-01-01 \
  --end-date 2024-01-31 \
  --symbols SOLUSDT,SOONUSDT
```

### Shadow режим валідація:
```bash
# Запуск у shadow режимі для валідації
DRY_RUN=true python -m skalp_bot.runner.run_live_aurora \
  --config profiles/my_strategy.yaml
```

## 📈 Performance аналіз

Профілі автоматично генерують метрики:

### Per-Profile метрики:
- **Total P&L** по профілю
- **Sharpe Ratio** для комбінації символів  
- **Max Drawdown** портфелю
- **Symbol correlation** динаміка
- **Parent-Child efficiency** (якщо використовується)

### Аналіз в logs:
```bash
# Метрики по профілю
grep "PROFILE.METRICS" logs/latest/aurora_events.jsonl

# Parent-child performance  
grep "PARENT_GATE" logs/latest/aurora_events.jsonl
```

## 🚨 Troubleshooting

### Типові проблеми профілів:

1. **"Parent-child correlation too low"**
   - Зменшіть `z_threshold`
   - Збільшіть `lookback_s`
   - Перевірте що символи справді корельовані

2. **"Cross-symbol exposure limit exceeded"**
   - Зменшіть `max_notional_usd` per symbol
   - Збільшіть `max_total_exposure_usd`
   - Перевірте логіку sizing

3. **"Profile config validation failed"**
   - Перевірте синтаксис YAML
   - Перевірте що всі required поля присутні
   - Запустіть валідацію: `python tools/config_cli.py validate`

### Debug профілю:
```yaml
# Додайте в профіль для debug
observability:
  debug_mode: true
  log_all_signals: true
  metric_frequency_s: 5
```