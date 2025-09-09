# Order Types Matrix: Binance USDT-M Futures Support

## Огляд
Цей документ містить матрицю підтримки ордерів та ф’ючерс-налаштувань для Binance USDT-M Futures API. Інформація зібрана з коду Aurora та конфігураційних файлів.

## Order Types

| Order Type | Підтримано | Файл/рядок | Тест є | Примітки |
|------------|------------|------------|--------|----------|
| LIMIT | ✅ Так | `skalp_bot/exch/ccxt_binance.py:313` | ✅ `tests/test_exchange_adapters.py:77` | Використовується для maker ордерів |
| MARKET | ✅ Так | `skalp_bot/runner/run_live_aurora.py:472` | ✅ `tests/unit/test_ccxt_binance_complete.py:232` | Використовується для taker ордерів |
| STOP | ❌ Ні | - | ❌ | Не знайдено у коді |
| STOP_MARKET | ❌ Ні | - | ❌ | Не знайдено у коді |
| TAKE_PROFIT | ❌ Ні | - | ❌ | Не знайдено у коді |
| TP_MARKET | ❌ Ні | - | ❌ | Не знайдено у коді |
| TRAILING_STOP_MARKET | ❌ Ні | - | ❌ | Не знайдено у коді |

## TimeInForce

| TimeInForce | Підтримано | Файл/рядок | Тест є | Примітки |
|-------------|------------|------------|--------|----------|
| GTC | ✅ Так | `skalp_bot/exch/ccxt_binance.py:313` | ✅ `tests/unit/test_ccxt_binance_complete.py:229` | За замовчуванням для limit ордерів |
| IOC | ✅ Так | `core/types.py:52` | ✅ `tests/unit/test_shadow_broker_complete.py:525` | Підтримується у типах та тестах |
| FOK | ✅ Так | `core/types.py:53` | ✅ `tests/unit/test_shadow_broker_complete.py:560` | Підтримується у типах та тестах |

## Прапори

| Прапор | Підтримано | Файл/рядок | Тест є | Примітки |
|--------|------------|------------|--------|----------|
| reduceOnly | ✅ Так | `skalp_bot/exch/ccxt_binance.py:317` | ✅ `tests/unit/test_ccxt_binance_complete.py:276` | Використовується для close позицій |
| postOnly | ❌ Ні | - | ❌ | Не знайдено у коді |
| priceProtect | ❌ Ні | - | ❌ | Не знайдено у коді |
| workingType | ❌ Ні | - | ❌ | Не знайдено у коді |

## Режими

| Режим | Підтримано | Файл/рядок | Тест є | Примітки |
|-------|------------|------------|--------|----------|
| HedgeMode (dual) | ❌ Ні | - | ❌ | Не знайдено у коді |
| OneWay | ❌ Ні | - | ❌ | Не знайдено у коді |
| Cross Margin | ❌ Ні | - | ❌ | Не знайдено у коді |
| Isolated Margin | ❌ Ні | - | ❌ | Не знайдено у коді |
| Leverage per symbol | ✅ Так | `configs/aurora/testnet.yaml:13` | ✅ `tests/test_sizing_kelly.py:283` | Налаштовується у конфігах |

## Тригери

| Тригер | Підтримано | Файл/рядок | Тест є | Примітки |
|--------|------------|------------|--------|----------|
| Mark Price | ❌ Ні | - | ❌ | Не знайдено у коді |
| Last Price | ❌ Ні | - | ❌ | Не знайдено у коді |
| SL (Stop Loss) | ❌ Ні | - | ❌ | Не знайдено у коді (тільки SLA) |
| TP (Take Profit) | ✅ Так | `skalp_bot/runner/run_live_aurora.py:523` | ❌ | Простий TP для LONG позицій |
| Trailing Stop | ❌ Ні | - | ❌ | Не знайдено у коді |

## Рейт-ліміти та ідемпотентність

| Функціонал | Підтримано | Файл/рядок | Тест є | Примітки |
|------------|------------|------------|--------|----------|
| Rate Limits | ✅ Так | `tools/auroractl.py:292` | ✅ `tools/exchange_smoke/binance_smoke.py:137` | enableRateLimit у CCXT |
| Idempotency | ✅ Так | `skalp_bot/runner/run_live_aurora.py:456` | ✅ `tests/unit/test_execution_idempotency.py` | client_oid для уникнення дублікатів |
| Sequence | ❌ Ні | - | ❌ | Не знайдено у коді |

## Підсумок підтримки

### Підтримувані функції:
- ✅ LIMIT та MARKET ордери
- ✅ GTC, IOC, FOK TimeInForce
- ✅ reduceOnly для close позицій
- ✅ Leverage налаштування
- ✅ Простий Take Profit для LONG
- ✅ Rate limiting
- ✅ Idempotency через client_oid

### Непідтримувані функції:
- ❌ STOP, STOP_MARKET, TAKE_PROFIT, TP_MARKET, TRAILING_STOP_MARKET ордери
- ❌ postOnly, priceProtect, workingType прапори
- ❌ HedgeMode, OneWay, Cross/Isolated margin режими
- ❌ Mark/Last price тригери
- ❌ Stop Loss та Trailing Stop
- ❌ Sequence numbering

### Рекомендації для розширення:
1. Додати підтримку STOP/TAKE_PROFIT ордерів через CCXT
2. Впровадити postOnly для maker-only стратегій
3. Додати Stop Loss та Trailing Stop логіку
4. Впровадити margin mode налаштування
5. Додати sequence numbering для ордерів

## Джерела інформації:
- Код: `skalp_bot/exch/ccxt_binance.py`, `skalp_bot/runner/run_live_aurora.py`
- Конфіги: `configs/aurora/testnet.yaml`, `profiles/btc_production_testnet.yaml`
- Тести: `tests/unit/test_ccxt_binance_complete.py`, `tests/unit/test_shadow_broker_complete.py`