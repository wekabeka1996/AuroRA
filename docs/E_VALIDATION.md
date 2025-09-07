# E-Validation (Futures Only, UM USDT-M)

Автоматизований аудит сценаріїв E0–E10 для скальп-бота на Binance USDT-M Futures. Мета — перевірка перед релізом без запуску додаткових «стартових» скриптів: ми лише читаємо вже наявні артефакти (логи, метрики) і формуємо sign-off.

## 1. Передумови

| Параметр | Значення / Вимога |
|----------|-------------------|
| EXCHANGE_ID | `binanceusdm` |
| BINANCE_ENV | `testnet` (або `prod` для фінального підпису) |
| AURORA_MODE | `live` |
| DRY_RUN | `true` для E1, далі `false` для реального тестнет циклу |
| AURORA_SESSION_DIR | Один каталог для API та бота (`logs/e_session_*`) |
| Acceptance env | НЕ встановлюємо (`AURORA_ACCEPTANCE_MODE` відсутній) |
| Ports | API: `:8037/metrics`, Bot: свій `METRICS_PORT` (напр. 9102) |

Початково: запусти API і бота (див. приклади нижче), дочекайся появи файлів `aurora_events.jsonl`, `orders_{denied,failed,success}.jsonl`.

## 2. Мінімальний запуск

### API
```bash
AURORA_API_TOKEN=accept \
AURORA_SESSION_DIR=logs/e2_session \
METRICS_PORT=9101 \
uvicorn api.service:app --host 127.0.0.1 --port 8037 --workers 1
```

### BOT (E2+)
```bash
AURORA_MODE=live \
DRY_RUN=false \
BINANCE_ENV=testnet \
EXCHANGE_ID=binanceusdm \
AURORA_SESSION_DIR=logs/e2_session \
AURORA_BASE_URL=http://127.0.0.1:8037 \
LEVERAGE=5 MARGIN_TYPE=cross \
METRICS_PORT=9102 \
python -m skalp_bot.scripts.run_live_aurora --config profiles/sol_soon_base.yaml
```
> Для E1 змінити `DRY_RUN=true`.

## 3. Інструмент: `tools/e_validation.py`

CLI для читання артефактів і формування допоміжних файлів.

### Підкоманди
| Команда | Опис |
|---------|------|
| `env-snapshot` | Зняти підмножину ENV (E0) |
| `metrics-scrape` | Завантажити `/metrics`, пропарсити deny counters |
| `lifecycle` | Реконструювати хронологію ордерів (success/failed/denied) |
| `deny-counts` | Порахувати `reason_code` у `orders_denied.jsonl` |
| `tree` | Перелік core файлів сесії з SHA256, розмірами й кількістю рядків |
| `signoff` | Структурований фінальний звіт (E10) |

### Приклади

E0 (env):
```bash
python tools/e_validation.py env-snapshot --out artifacts/E0_env_snapshot.txt
```

Метрики API / бота:
```bash
python tools/e_validation.py metrics-scrape --url http://127.0.0.1:8037/metrics  --out artifacts/E1_api_metrics.txt
python tools/e_validation.py metrics-scrape --url http://127.0.0.1:9102/metrics  --out artifacts/E1_bot_metrics.txt
```

Життєвий цикл та deny:
```bash
python tools/e_validation.py lifecycle   --session logs/e2_session --out artifacts/E2_lifecycle.jsonl
python tools/e_validation.py deny-counts --session logs/e2_session --out artifacts/E8_deny_counts.txt
python tools/e_validation.py tree        --session logs/e2_session --out artifacts/E9_tree.txt
python tools/e_validation.py signoff     --session logs/e2_session --out artifacts/E10_signoff.json
```

## 4. Критерії PASS по етапах

| Етап | PASS Критерій |
|------|---------------|
| E1 | `/metrics` 200; у `aurora_events.jsonl` існує `PRETRADE.CHECK`; є записи у `orders_denied.jsonl` з нормалізованим `reason_code` |
| E2 | Пара подій open (ORDER.SUBMIT→ACK→FILL) + закриття reduceOnly (SUBMIT→ACK→FILL) |
| E3 | POST-only «would trade» не сабмітиться; deny-код класифіковано |
| E4 | Немає біржових помилок -1013/-1111/-4164 у `orders_failed.jsonl` (перехоплено pre-trade) |
| E5 | Після close позиція ≈ 0; усі close мають `reduceOnly=true` |
| E6 | Після рестарту API бот відновив pretrade, немає лавини неконтрольованих сабмітів |
| E7 | p95 latency у межах внутрішнього SLA; 429 при наявності оброблено (backoff) |
| E8 | Лічильники governance deny у metrics == підрахунку в `orders_denied.jsonl` |
| E9 | Один набір `orders_*` файлів у session dir, без дублювання дерев |
| E10| `E10_signoff.json` містить hashes + fills/failed/denies + top_reason_codes + latency p50/p95 |

## 5. Формат `E10_signoff.json`
```json
{
  "version": "E10-signoff-v1",
  "generated_utc": "...Z",
  "session_dir": "logs/e2_session",
  "hashes": {
    "aurora_events.jsonl": {"sha256": "...", "bytes": 123, "lines": 321},
    "orders_success.jsonl": {...},
    "orders_failed.jsonl": {...},
    "orders_denied.jsonl": {...}
  },
  "orders": {
    "fills": 10,
    "failed": 0,
    "denies": 5,
    "top_reason_codes": [{"code": "WHY_GOV_SPRT_REJECT", "count": 3}]
  },
  "latency": {"available": true, "p50_ms": 12.5, "p95_ms": 31.2 }
}
```

## 6. Метрики та лічильники
- Парсер шукає deny counters за шаблоном у рядках виду `aurora_...denies...{code="X"} <value>`.
- Governance перехресно звіряється (E8) через `deny-counts` + `metrics-scrape` вручну або зовнішнім скриптом.

## 7. Типові проблеми
| Симптом | Причина | Дія |
|---------|---------|-----|
| Порожній `orders_success.jsonl` | Ще не було угод | Довше проганяти або знизити фільтри / розмір |
| Відсутній latency | Немає полів / низька активність | Почекати більше або активувати реальні сабміти |
| Множинні session каталоги | Конкурентний запуск із різними `AURORA_SESSION_DIR` | Вирівняти env перед стартом |
| Біржові помилки -1013/-1111 | Неправильна квантизація | Перевірити нормалізацію та профіль sizing |

## 8. Безпека
- **Не** використовувати acceptance режим.
- Починати з DRY_RUN=true (E1), далі вимикати для реального циклу.
- Відокремлювати testnet від prod ключів та `.env`.

## 9. Наступні розширення (опційно)
- Автоматична валідація E2/E5 через REST позицій (якщо додано API для позицій).
- Вбудований порівняльний диф між двома сесіями.
- PGP підпис signoff файлу.

---
Цей документ охоплює базові сценарії E-валідації та узгоджений з інструментом `e_validation.py`.
