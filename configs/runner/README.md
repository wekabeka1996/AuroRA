# Aurora Runner (WiseScalp) Configuration Documentation

Цей документ описує конфігураційні файли для Aurora Runner - торгового бота WiseScalp.

## 📁 Структура конфігурацій Runner

```
configs/runner/
├── base.yaml         # Базові налаштування runner
├── test_param.yaml   # Тестові параметри
└── README.md         # Цей файл
```

## 🎯 Призначення Runner конфігурацій

Runner конфігурації керують поведінкою торгового бота WiseScalp, який:
- Генерує alpha сигнали
- Консультується з Aurora API перед розміщенням трейдів
- Управляє позиціями та ризиками
- Відстежує performance метрики

## 📋 Опис конфігураційних файлів

### `base.yaml` - Базова конфігурація Runner

**Призначення**: Фундаментальні налаштування для роботи торгового бота.

**Основні секції**:

#### Trading Configuration:
```yaml
universe:
  symbols: [BTCUSDT, ETHUSDT]  # Торгові пари
  
sizing:
  limits:
    min_notional_usd: 10       # Мінімальний розмір ордера
    max_notional_usd: 1000     # Максимальний розмір ордера
  kelly_scaler: 0.1            # Скалер для Kelly criterion
```

#### Execution Settings:
```yaml
execution:
  broker: shadow                # shadow/live
  router:
    spread_limit_bps: 15       # Максимальний spread у bps
  sla:
    max_latency_ms: 250        # Максимальна латентність
```

#### Risk Management:
```yaml
reward:
  ttl_minutes: 20              # TTL для reward обчислень
  take_profit_bps: 20          # Take profit у bps
  stop_loss_bps: 40            # Stop loss у bps
  be_break_even_bps: 6         # Break-even рівень
```

#### Alpha Signal Configuration:
```yaml
signal:
  features:
    obi_enabled: true          # Order Book Imbalance
    tfi_enabled: true          # Trade Flow Imbalance
    microprice_enabled: true   # Microprice features
  
  model:
    type: "hazard"             # Тип моделі
    lookback_ms: 5000          # Lookback вікно
```

### `test_param.yaml` - Тестові параметри

**Призначення**: Спеціалізована конфігурація для тестування та експериментів.

**Ключові особливості**:
- Зменшені розміри позицій для безпечного тестування
- Коротші TTL для швидких тестів  
- Увімкнені додаткові логи та метрики
- Тестові символи (можливо, mock data)

**Структура**:
```yaml
# Test-specific overrides
universe:
  symbols: [BTCUSDT]           # Один символ для фокусу
  
sizing:
  limits:
    max_notional_usd: 50       # Малі розміри для тестів
  kelly_scaler: 0.05           # Консервативний скалер

testing:
  mock_mode: true              # Увімкнути mock режим
  log_level: "DEBUG"           # Детальне логування
  metrics_interval_s: 1        # Часті метрики
```

## 🔧 Інтеграція з Aurora API

Runner конфігурації працюють разом з Aurora API конфігураціями:

### Workflow:
1. **Signal Generation**: Runner генерує торговий сигнал
2. **Pre-trade Check**: Консультація з Aurora API `/pretrade/check`
3. **Order Execution**: Якщо Aurora дозволяє - розміщення ордера
4. **Position Management**: Відстеження та управління позицією

### API Integration Settings:
```yaml
aurora_api:
  base_url: "http://localhost:8080"  # Aurora API endpoint
  timeout_ms: 500                    # API timeout
  retry_attempts: 3                  # Кількість retry
```

## 🚀 Запуск Runner з різними конфігураціями

### Використання базової конфігурації:
```bash
python -m skalp_bot.runner.run_live_aurora --config configs/runner/base.yaml
```

### Використання тестових параметрів:
```bash  
python -m skalp_bot.runner.run_live_aurora --config configs/runner/test_param.yaml
```

### Bare name resolution (без повного шляху):
```bash
# Автоматично знайде configs/runner/test_param.yaml
python -m skalp_bot.runner.run_live_aurora --config test_param
```

## 🎛️ Environment Variables Override

Runner підтримує override через змінні середовища:

```bash
# Trading mode
export DRY_RUN=true                    # Shadow trading mode
export BINANCE_ENV=testnet             # Binance testnet

# Risk parameters  
export AURORA_MAX_NOTIONAL_USD=100     # Override max position size
export AURORA_KELLY_SCALER=0.05        # Override Kelly scaler

# API settings
export AURORA_API_BASE_URL=http://localhost:8080
export AURORA_API_TIMEOUT_MS=1000
```

## 🔄 Multi-Symbol Configuration

Runner підтримує торгівлю кількома символами одночасно:

### Приклад конфігурації:
```yaml
universe:
  symbols: [SOLUSDT, SOONUSDT]
  
# Per-symbol overrides
symbol_overrides:
  SOLUSDT:
    sizing:
      max_notional_usd: 100
    signal:
      features:
        obi_weight: 0.6
        
  SOONUSDT:
    sizing:
      max_notional_usd: 50  
    signal:
      features:
        obi_weight: 0.4
```

## 📊 Performance Monitoring

Runner автоматично відстежує метрики:

### Встроєні метрики:
- **P&L**: Прибуток/збиток по символах
- **Sharpe Ratio**: Ризик-коригована прибутковість
- **Max Drawdown**: Максимальна просадка
- **Win Rate**: Відсоток прибуткових трейдів
- **Alpha Decay**: Деградація сигналу

### Конфігурація метрик:
```yaml
observability:
  metrics:
    enabled: true
    interval_s: 30              # Частота оновлення
    retention_hours: 24         # Час зберігання
  
  events:
    log_trades: true            # Логувати всі трейди
    log_signals: false          # Логувати сигнали (verbose)
```

## 🔐 Security для Runner

### API ключі Binance:
```yaml
exchange:
  binance:
    api_key: "${BINANCE_API_KEY}"        # З environment
    api_secret: "${BINANCE_API_SECRET}"  # З environment
    testnet: true                        # Для безпеки
```

**⚠️ НІКОЛИ не зберігайте API ключі у YAML файлах!**

### Best Practices:
1. Використовуйте environment variables для credentials
2. Увімкніть IP whitelist у Binance
3. Встановіть мінімальні необхідні permissions
4. Регулярно ротуйте API ключі

## 🧪 Testing Runner Configuration

### Валідація конфігурації:
```bash
# Перевірка синтаксису
python -c "
import yaml
with open('configs/runner/base.yaml') as f:
    config = yaml.safe_load(f)
    print('✅ Configuration valid')
"

# Dry run тест
DRY_RUN=true python -m skalp_bot.runner.run_live_aurora --config test_param
```

### Mock режим для тестування:
```yaml
testing:
  mock_mode: true
  mock_data:
    price_feed: "data/mock_prices.json"
    orderbook: "data/mock_orderbook.json"
```

## 🚨 Troubleshooting Runner

### Типові проблеми:

1. **"Failed to connect to Aurora API"**
   - Перевірте що Aurora API запущений
   - Перевірте `aurora_api.base_url`
   - Перевірте токени автентифікації

2. **"Invalid symbol configuration"**
   - Перевірте що символи існують на exchange
   - Перевірте format символів (BTCUSDT, не BTC/USDT)

3. **"Position size validation failed"**
   - Перевірте `min_notional_usd` та `max_notional_usd`
   - Перевірте балансу на рахунку

4. **"Model loading failed"**
   - Перевірте шляхи до model файлів
   - Перевірте permissions на файли
   - Перевірте format моделі

### Debug режим:
```yaml
logging:
  level: "DEBUG"
  handlers:
    - console
    - file: "logs/runner_debug.log"
```

## 📚 Додаткові ресурси

- `profiles/` - Multi-symbol профілі (sol_soon_base.yaml)
- `skalp_bot/configs/` - Legacy конфігурації (deprecated)
- `tools/auroractl.py` - Utility для управління конфігураціями