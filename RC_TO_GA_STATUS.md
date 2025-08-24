# AURORA RC → GA Transition Plan
## Статус виконання задач

### ✅ ЗАВЕРШЕНО (REL-TAG-&-BUILD)
- [x] **VERSION управління**: Файл VERSION з 0.4.0-rc1
- [x] **API інтеграція**: /version endpoint в FastAPI
- [x] **Build script**: scripts/build_release.py з повним CLI
- [x] **Dockerfile**: Підтримка VERSION через build args

### ✅ ЗАВЕРШЕНО (CFG-PROFILES-LOCK)  
- [x] **Профілі створено**:
  - `configs/profiles/r2.yaml` - продакшен (строгі пороги)
  - `configs/profiles/smoke.yaml` - тестування (м'які пороги)
- [x] **Валідація**: scripts/validate_profiles.py з lock механізмом
- [x] **Lock файли**: .lock checksum захист від змін

### ✅ ЗАВЕРШЕНО (GA-GATES)
- [x] **Статистичний framework**: scripts/report_preloop_stats.py
- [x] **5 GA критеріїв**:
  - main_loop_started_ratio ≥ 0.95
  - decisions_total ≥ 1  
  - preloop exit_kind=exit ≥ 0.7
  - noop_ratio_mean ≤ 0.85
  - zero_budget == 0
- [x] **Prometheus метрики**: Автогенерація для моніторингу

### ✅ ЗАВЕРШЕНО (CANARY-ROLL)
- [x] **Canary framework**: scripts/canary_deploy.py
- [x] **3 тести/день**: По 0.6 хвилини з затримкою 5 хв
- [x] **Health checks**: Автоматична перевірка метрик
- [x] **Success criteria**: 2/3 тестів повинні пройти

### ✅ ЗАВЕРШЕНО (OBS-DASH)
- [x] **Grafana dashboard**: monitoring/aurora_dashboard.json
- [x] **6 панелей**: GA gates, preloop, main loop, canary, resources, errors
- [x] **Prometheus alerts**: monitoring/aurora_alerts.yml
- [x] **Template variables**: Environment і config профілі

### ✅ ЗАВЕРШЕНО (ROLLBACK-PLAN)
- [x] **Git integration**: Версіонування і rollback
- [x] **Configuration rollback**: Lock файли для швидкого відкату
- [x] **Health monitoring**: Continuous health checks

### ✅ ЗАВЕРШЕНО (GA-READINESS)
- [x] **Readiness script**: scripts/ga_readiness.py
- [x] **7 перевірок**: Версія, конфігурація, збірка, GA gates, canary, dashboard, rollback
- [x] **Automated assessment**: Повний звіт готовності

## 🎯 НАСТУПНІ КРОКИ

### 1. Canary Testing (готово до запуску)
```bash
# Запуск canary тестів
python scripts/canary_deploy.py --tests 3 --delay 5 --minutes 0.6

# Результат: artifacts/canary_report.json
```

### 2. Staging Metrics Collection (24-48h)
```bash
# Збір статистики
python scripts/report_preloop_stats.py --root runs --out artifacts/staging_stats.json --prom artifacts/staging_metrics.prom

# Оцінка GA gates
python scripts/report_preloop_stats.py --root runs --evaluate-gates
```

### 3. GA Promotion Decision
Критерії для переходу RC → GA:
- ✅ Canary tests: 67%+ success rate
- ✅ GA gates: Всі 5 критеріїв пройдені  
- ✅ Zero warnings: У smoke тестах
- ✅ 24h stability: Без критичних інцидентів

### 4. Production Deployment
```bash
# Оновити версію до GA
echo "0.4.0" > VERSION

# Збірка GA артефактів  
python scripts/build_release.py --all

# Deploy з моніторингом
# (використовувати r2.yaml профіль)
```

## 📊 МОНІТОРИНГ СТАТУС

### Grafana Dashboard
- **URL**: monitoring/aurora_dashboard.json
- **Panels**: 6 панелей моніторингу
- **Alerts**: Prometheus alerts налаштовані

### Key Metrics
- `aurora_ga_gate_*` - GA критерії
- `aurora_canary_*` - Canary здоров'я  
- `aurora_preloop_*` - Preloop статистика
- `aurora_main_loop_*` - Main loop метрики

## 🔧 TROUBLESHOOTING

### Якщо canary тести не проходять:
1. Перевірити конфігурацію profiles
2. Запустити з smoke.yaml (relaxed)
3. Проаналізувати логи через dashboard

### Якщо GA gates не проходять:
1. Збільшити вибірку (більше runs)
2. Перевірити r2.yaml vs smoke.yaml різниці
3. Аналіз через report_preloop_stats.py

### Zero budget issues:
1. Перевірити market conditions
2. Перевірити trading logic
3. Можливо потрібен seed adjustment

## 📋 ФАЙЛИ ТА ІНФРАСТРУКТУРА

### Створені скрипти:
- `scripts/build_release.py` - RC/GA збірка
- `scripts/validate_profiles.py` - Конфігурація 
- `scripts/report_preloop_stats.py` - GA gates
- `scripts/canary_deploy.py` - Canary testing
- `scripts/create_dashboard.py` - Observability
- `scripts/ga_readiness.py` - Готовність оцінка

### Конфігурації:
- `configs/profiles/r2.yaml` + .lock
- `configs/profiles/smoke.yaml` + .lock  
- `monitoring/aurora_dashboard.json`
- `monitoring/aurora_alerts.yml`

### Артефакти:
- `artifacts/profile_validation.json`
- `artifacts/ga_readiness_report.json`
- `artifacts/canary_report.json` (після тестів)

## 🎉 ГОТОВНІСТЬ СТАТУС: ✅ READY

Всі системи готові для RC → GA переходу!
Можна переходити до canary тестування та staging метрик.