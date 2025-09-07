# P3-D: Live Dashboards / Live Gauges

## Загальний огляд

P3-D забезпечує real-time моніторинг торгової системи Aurora через SSE (Server-Sent Events) dashboard з live метриками та візуалізацією.

## Архітектура

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│  Aurora Runner  │───▶│  Live Feed SSE   │───▶│ React Dashboard │
│                 │    │  Server          │    │                 │
│  JSONL Logs     │    │  (Port 8001)     │    │  (Port 3000)    │
└─────────────────┘    └──────────────────┘    └─────────────────┘
```

### Компоненти

1. **Live Feed Server** (`tools/live_feed.py`)
   - SSE сервер на Starlette/uvicorn
   - Async JSONL tail reading
   - Rolling window aggregation (5 хв)
   - Real-time метрики

2. **React Dashboard** (`tools/dashboard/`)
   - Real-time UI з live відображенням
   - SSE підключення до backend
   - Графіки latency та KPI
   - Responsive design

3. **Runner Integration**
   - `--telemetry` CLI flag
   - Автоматичний запуск live feed
   - OBS.TELEMETRY.* events

## Використання

### Запуск з telemetry

```bash
# Запуск runner з telemetry сервером
python -m skalp_bot.runner.run_live_aurora --telemetry

# Live feed сервер буде доступний на http://localhost:8001
```

### Запуск dashboard

```bash
# Встановлення залежностей
cd tools/dashboard
npm install

# Запуск React додатку
npm start

# Dashboard доступний на http://localhost:3000
```

### Використання dashboard launcher

```bash
# Автоматичний launcher
python tools/dashboard_launcher.py

# З custom портом
python tools/dashboard_launcher.py --port 3001
```

## SSE API Endpoints

### `/sse` - Event Stream
Live stream метрик у форматі Server-Sent Events:

```javascript
// Підключення до SSE
const eventSource = new EventSource('http://localhost:8001/sse');

eventSource.onmessage = (event) => {
  const metrics = JSON.parse(event.data);
  // Process real-time metrics
};
```

### `/health` - Health Check
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### `/status` - Current Metrics
```json
{
  "ts_ns": 1704110400000000000,
  "orders": {
    "submitted": 150,
    "ack": 148,
    "filled": 140,
    "cancelled": 8,
    "denied": 2,
    "failed": 0
  },
  "routes": {
    "maker": 120,
    "taker": 20,
    "deny": 2,
    "cancel": 8
  },
  "latency": {
    "decision_ms_p50": 12.5,
    "decision_ms_p90": 28.0,
    "to_first_fill_ms_p50": 45.2,
    "to_first_fill_ms_p90": 89.5
  },
  "governance": {
    "alpha": {"score": 0.85, "decision": "allow"},
    "sprt": {"updates": 15, "final": {"ratio": 2.1}}
  },
  "xai": {
    "why_code_counts": {"WHY_001": 45, "WHY_002": 23}
  },
  "circuit_breaker": {
    "triggered": false,
    "reason": null
  },
  "pending": {"pending_orders": 5},
  "window_events": 1250
}
```

## Метрики Dashboard

### Orders Panel
- **Submitted**: Загальна кількість поданих ордерів
- **Filled**: Виконані ордери
- **Cancelled**: Скасовані ордери  
- **Failed**: Невдалі ордери
- **Fill Rate**: Відсоток виконання (filled/submitted * 100%)

### Routes Panel
- **Maker**: Maker роути (ліквідність)
- **Taker**: Taker роути (агресивні)
- **Denied**: Відхилені роути
- **Cancelled**: Скасовані роути
- **Taker Rate**: Відсоток taker рутів

### Latency Panel
- **P50**: Медіанна латентність
- **P90**: 90-й персентиль
- **P99**: 99-й персентиль  
- **Pending**: Очікуючі операції

### Governance Panel
- **Alpha Score**: Поточний alpha score
- **SPRT Ratio**: Sequential probability ratio
- **Decisions**: Кількість governance рішень
- **Circuit Breaker**: Статус аварійного вимкнення

### Latency Chart
Real-time графік P50/P90/P99 латентності з rolling window.

## Конфігурація

### Live Feed Server
```python
# Запуск з custom параметрами
python -m tools.live_feed \
  --session-dir /path/to/session \
  --port 8002 \
  --window-seconds 600 \
  --debug
```

### Dashboard Environment
```bash
# React environment variables
PORT=3000
BROWSER=none
REACT_APP_TELEMETRY_URL=http://localhost:8001
```

## Розробка

### Додавання нових метрик

1. **Backend** (live_feed.py):
```python
# В LiveAggregator.process_event()
if event_code == "NEW.EVENT":
    self.custom_metric += 1

# В get_current_metrics()
return {
    # ...existing metrics
    "custom": {"metric": self.custom_metric}
}
```

2. **Frontend** (App.js):
```javascript
// В React компоненті
const customValue = metrics.custom?.metric || 0;

// Додати в UI
<div className="metric-value">{customValue}</div>
```

### Тестування
```bash
# Запуск всіх P3-D тестів
python -m pytest tests/integration/test_p3d_live_dashboard.py -v

# Тестування компонентів
python -c "
from tools.live_feed import LiveAggregator
agg = LiveAggregator()
print('✅ Live aggregator works')
"
```

## Troubleshooting

### SSE Connection Issues
- Перевірте що live feed server запущений на правильному порту
- Переконайтеся що CORS настроений правильно
- Перевірте firewall settings

### Dashboard не запускається
- Встановіть Node.js та npm
- Запустіть `npm install` в `tools/dashboard/`
- Перевірте що порт 3000 вільний

### Метрики не оновлюються
- Перевірте що JSONL logs генеруються
- Переконайтеся що session directory правильний
- Перевірте browser console для помилок

### Windows-specific Issues
- Використовуйте bash.exe або PowerShell
- Перевірте path separators у конфігурації
- Встановіть відповідні SSL certificates для HTTPS

## Acceptance Criteria ✅

- [x] SSE сервер з real-time метриками
- [x] React dashboard з live оновленнями  
- [x] Інтеграція з runner через --telemetry flag
- [x] Rolling window aggregation (5 хв)
- [x] Latency percentiles (P50/P90/P99)
- [x] Orders, routes, governance метрики
- [x] Circuit breaker моніторинг
- [x] Responsive UI design
- [x] Cross-platform підтримка
- [x] Comprehensive integration tests
- [x] CLI tools і launchers
- [x] Health check endpoints
- [x] Documentation та troubleshooting guide

P3-D Live Dashboards успішно реалізовано! 🎉