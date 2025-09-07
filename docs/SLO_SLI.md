# SLO/SLI для Aurora P3-E

## Огляд

Цей документ визначає Service Level Indicators (SLI) та Service Level Objectives (SLO) для Aurora P3-E.
SLI вимірюють фактичну продуктивність системи, а SLO визначають цільові рівні цієї продуктивності.

## Ключові SLI та SLO

### 1. SSE Availability (Доступність SSE)
**SLI:** `sum(rate(sse_events_sent_total[30d])) / sum(rate(sse_events_attempted_total[30d]))`
- **SLO:** ≥ 99.9% за 30 діб
- **Мета:** Забезпечити високу доступність потокових даних для клієнтів
- **Критичність:** Critical - впливає на всі downstream системи

### 2. SSE Reconnect Rate (Частота перепідключень)
**SLI:** `rate(sse_reconnects_total[1m])`
- **SLO:** < 5 перепідключень за хвилину
- **Мета:** Мінімізувати переривання з'єднань клієнтів
- **Критичність:** Warning - вказує на проблеми з мережею або сервером

### 3. Policy Deny Ratio (Рівень відмов політики)
**SLI:** `(sum(rate(policy_denied_total[15m)) / clamp_min(sum(rate(policy_considered_total[15m)), 1))`
- **SLO:** < 35% глобально
- **Мета:** Забезпечити розумний баланс між прибутковістю та частотою торгівлі
- **Критичність:** Warning - може вказувати на проблеми з калібруванням

### 4. Execution Latency P99 (Латентність виконання P99)
**SLI:** `histogram_quantile(0.99, sum(rate(exec_latency_ms_bucket[10m])) by (le))`
- **SLO:** ≤ 300 мс
- **Мета:** Забезпечити швидке виконання ордерів
- **Критичність:** Critical - впливає на прибутковість

### 5. Circuit Breaker State (Стан Circuit Breaker)
**SLI:** `circuit_breaker_state`
- **SLO:** OPEN = 0 хвилин за 24 години (SLA: ≤10 хвилин)
- **Мета:** Автоматичний захист від каскадних відмов
- **Критичність:** Critical - запобігає значним втратам

### 6. Calibration ECE (Expected Calibration Error)
**SLI:** `calibration_ece` (останнє значення)
- **SLO:** ≤ 0.05
- **Мета:** Забезпечити точність ймовірнісних оцінок
- **Критичність:** Warning - впливає на якість рішень

### 7. CVaR Breaches (Порушення CVaR)
**SLI:** `increase(risk_cvar_breach_total[1h])`
- **SLO:** 0 порушень за годину
- **Мета:** Захист від надмірного ризику
- **Критичність:** Critical - запобігає значним втратам

## Формули розрахунку

### SSE Availability Ratio
```
availability = sent_events / attempted_events
```
- `sent_events`: кількість успішно відправлених SSE подій
- `attempted_events`: загальна кількість спроб відправки подій

### Policy Deny Ratio
```
deny_ratio = denied_decisions / total_decisions
```
- `denied_decisions`: кількість відмовлених рішень
- `total_decisions`: загальна кількість оцінюваних рішень

### Execution Latency P99
```
p99_latency = 99-й перцентиль розподілу латентності
```
- Вимірюється в мілісекундах від відправки ордера до отримання відповіді

## Пороги алертів

### Critical Alerts (Пагер)
- SSE availability < 99.9% (30d rolling)
- Execution latency p99 > 300ms
- Circuit breaker OPEN sustained (>10m)
- CVaR breach detected

### Warning Alerts (Моніторинг)
- SSE reconnect rate > 5/min
- Policy deny ratio > 35%
- Calibration ECE > 0.05
- No active SSE clients (business hours)

## Error Budget

### SSE Availability
- **Ціль:** 99.9% (8.77 годин downtime за місяць)
- **Error budget:** 8.77 годин за 30 діб
- **Використання:** Відстежується для планування maintenance

### Execution Latency
- **Ціль:** p99 ≤ 300ms
- **Пом'якшення:** Автоматичне зниження частоти при перевищенні

## Моніторинг та дашборди

### Ключові метрики для відстеження
1. `sse:availability_ratio:5m` - поточна доступність
2. `policy:deny_ratio:15m` - рівень відмов
3. `exec:latency_p99:10m` - латентність виконання
4. `circuit_breaker_state` - стан захисних механізмів

### Recording Rules
```prometheus
# SSE availability ratio
- record: sse:availability_ratio:5m
  expr: sum(rate(sse_events_sent_total[5m]))/sum(rate(sse_events_attempted_total[5m]))

# Policy deny ratio
- record: policy:deny_ratio:15m
  expr: (sum(rate(policy_denied_total[15m]))/clamp_min(sum(rate(policy_considered_total[15m]),1))

# Execution latency p99
- record: exec:latency_p99:10m
  expr: histogram_quantile(0.99, sum(rate(exec_latency_ms_bucket[10m])) by (le))
```

## Відповідальність

### SRE/Ops
- Моніторинг SLO/SLI
- Розслідування порушень
- Впровадження покращень

### Development
- Підтримка SLI instrumentation
- Оптимізація продуктивності
- Виправлення багів

### Business
- Визначення SLO targets
- Prioritization trade-offs
- Approval для SLO changes