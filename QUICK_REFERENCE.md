# 🚀 AURORA 0.4.0 GA - Quick Command Reference

## ⚡ INSTANT CUTOVER (Copy-Paste Ready)

### 1. Final Validation
```bash
python scripts/ga_gates_eval.py --critical && echo "✅ GATES PASS" || echo "❌ GATES FAIL"
```

### 2. Execute Cutover
```bash
python scripts/day0_cutover.py --confirm --profile r2 && echo "✅ CUTOVER SUCCESS" || echo "❌ CUTOVER FAILED"
```

### 3. Start Watch
```bash
nohup python scripts/watch_24h.py --output logs/ga_watch.log & echo "Watch PID: $!"
```

### 4. Verify Production
```bash
cat VERSION && curl -s localhost:8000/version | jq '.version'
```

---

## 🔥 EMERGENCY ROLLBACK

```bash
python scripts/emergency_rollback.py --force --confirm && echo "✅ ROLLBACK COMPLETE"
```

---

## 📊 HEALTH CHECKS

### Quick Status
```bash
python scripts/ga_gates_eval.py --quick --json | jq '.gates_passing'
```

### Detailed Report
```bash
python scripts/ga_gates_eval.py --full --output artifacts/health_$(date +%Y%m%d_%H%M).md
```

---

## 🎯 SUCCESS CRITERIA

**Day-0:** All 5 GA gates pass ✅  
**24h:** Zero exit=3 failures ✅  
**7-day:** Continuous stability ✅  

---

**Status: PRODUCTION READY** 🏆

---

## 🔐 Binance подключение (безопасная настройка)

1) Ключи API (НЕ коммитить!):
	- Создайте ключ/секрет в Binance (USDT-M Futures, если используете фьючерсы)
	- Установите переменные окружения:
	  - `BINANCE_API_KEY`
	  - `BINANCE_API_SECRET`

2) Конфиг бота: `skalp_bot/configs/default.yaml`
	- Секция `exchange`:
	  - `id`: `binanceusdm` (фьючерсы USDT-M) или `binance` (спот)
	  - `use_futures`: true/false
	  - `testnet`: true (песочница) / false (прод)
	  - `symbol`: "BTC/USDT"
	  - `leverage`: 10 (опционально)
	  - `api_key_env` / `api_secret_env`: имена env переменных
	- `dry_run: true` для безопасной проверки без ордеров.

3) Перед live:
	- `exchange.testnet: false`, `dry_run: false`
	- Проверьте лимиты в `execution` (trades_per_minute_limit, max_symbol_exposure_usdt, spread_guard_bps_max)
	- Убедитесь, что AURORA API отвечает (`/health`), и pre-trade gate даёт `allow=true` для тестового ордера.

Примечание: Никогда не храните ключи в файлах. Используйте переменные окружения.