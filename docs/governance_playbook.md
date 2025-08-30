# Governance Playbook

## Alpha-Spending Ledger Policies

### Overview
Alpha-spending ledger контролирует кумулятивные расходы уровня значимости (α) при множественных статистических тестах, предотвращая inflation Type I error.

### Supported Policies

#### 1. Pocock Policy
**Принцип:** Равномерное распределение α-budget между тестами
**Формула:** `α(t) = α_total / n_tests`
**Когда использовать:** Когда ожидаемое количество тестов известно заранее
**Преимущества:** Простота, консервативность
**Недостатки:** Может быть слишком строгим для малого числа тестов

#### 2. O'Brien-Fleming Policy
**Принцип:** α уменьшается со временем (более строгие тесты позже)
**Формула:** `α(t) = min(α_total, α_total * 2 / t)`
**Когда использовать:** Для последовательных тестов с накоплением данных
**Преимущества:** Адаптивность к времени, меньше false positives на поздних этапах
**Недостатки:** Сложнее интерпретировать

#### 3. Benjamini-Hochberg FDR Policy
**Принцип:** Контроль False Discovery Rate
**Формула:** `α(t) = α_total * t / n_tests`
**Когда использовать:** Для множественных сравнений, когда важен контроль FDR
**Преимущества:** Оптимально для множественных гипотез
**Недостатки:** Требует знания общего числа тестов

### Configuration

```python
from core.governance.composite_sprt import AlphaSpendingLedger

# Pocock policy
ledger = AlphaSpendingLedger(total_alpha=0.05, policy="pocock")
ledger.set_expected_tests(10)  # Ожидаем 10 тестов

# O'Brien-Fleming
ledger = AlphaSpendingLedger(total_alpha=0.05, policy="obf")

# BH-FDR
ledger = AlphaSpendingLedger(total_alpha=0.05, policy="bh-fdr")
ledger.set_expected_tests(20)
```

### Rollback Canary

#### Trigger Conditions
- `cumulative_alpha > total_alpha * 1.2` (20% превышение бюджета)
- 3 последовательных отклонения H0 при `p_value > 0.1`
- Tail index выходит за доверительный интервал на 3σ

#### Actions
1. **Warning:** Логирование в XAI с кодом `AURORA.RISK_WARN`
2. **Throttle:** Увеличение интервала между тестами на 50%
3. **Halt:** Полная остановка тестирования при `cumulative_alpha > total_alpha * 1.5`
4. **Reset:** Очистка ledger и перезапуск с новыми параметрами

#### Recovery
- Автоматическое восстановление через 5 минут при устранении причины
- Ручное подтверждение через CLI: `auroractl governance reset-ledger`

### Monitoring

#### Key Metrics
- `alpha_cumulative`: Текущие расходы α
- `alpha_remaining`: Остаток бюджета
- `n_tests_performed`: Количество выполненных тестов
- `policy_compliance`: Соответствие выбранной политике

#### Alerts
- `ALERT_ALPHA_BUDGET_80%`: 80% бюджета израсходовано
- `ALERT_ALPHA_BUDGET_EXCEEDED`: Бюджет превышен
- `ALERT_POLICY_VIOLATION`: Нарушение политики расходов

### Best Practices

1. **Выбор политики:** Pocock для простых случаев, OBF для последовательных тестов
2. **Мониторинг:** Регулярно проверять `ledger.get_policy_info()`
3. **Fallback:** Всегда иметь консервативный fallback при превышении бюджета
4. **Документация:** Логировать все решения с полной информацией о α-spending

### Integration Points

#### With SPRT
```python
sprt = create_gaussian_sprt(alpha_policy="pocock")
result = sprt.update(observation, model_h0, model_h1)
if result.alpha_spent > 0:
    # Проверить бюджет
    if not sprt.alpha_ledger.can_spend_alpha(result.alpha_spent):
        trigger_rollback()
```

#### With XAI Logging
Все решения автоматически логируются с полным контекстом α-spending:
```json
{
  "event_code": "SPRT.DECISION_H1",
  "alpha_spent": 0.002,
  "alpha_policy": "pocock",
  "alpha_ledger_info": {
    "cumulative_alpha": 0.023,
    "remaining_alpha": 0.027,
    "policy": "pocock"
  }
}
```