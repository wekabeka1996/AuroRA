# Copilot Instructions for this Repo — **Nonstop Mode v2** (Aurora × WiseScalp)




---

## 1) Big picture (узгоджено з SSOT)

* **Aurora (FastAPI)**: watchdog/health/metrics, pre‑trade gates, post‑trade events. Ендпоїнти: `/health`, `/metrics`, `/pretrade/check`, `/posttrade/log`.
* **WiseScalp (runner)**: мікроструктурна альфа (OBI/TFI/absorption/micro‑price) + виконання. **Завжди** викликає Aurora gate перед відправкою ордерів.
* **Новий v4‑min core**: `core/scalper/*`, `core/aurora/*`, `common/*`. Конфіги: `configs/*.yaml`.
* **Спостережуваність**: Prometheus `/metrics`, події JSONL: `logs/aurora_events.jsonl`; ордери розділені: `logs/orders_{success,failed,denied}.jsonl`.

---





---

## 5) Critical workflows (коротко)

* **Install+tests:** `python -m pip install -r requirements.txt -r requirements-dev.txt` → `pytest -q`.
* **API (локально):** `python api/service.py` → `GET /health`, `GET /metrics`.
* **Docker compose:** `docker compose up --build -d` (API :8000 / Grafana :3000 / Prometheus :9090).
* **Unified CLI:** `python tools/auroractl.py one-click --mode testnet --minutes 15 --preflight`.
* **Runner (shadow/paper):** налаштуй `.env` (див. `.env.example`), запусти `skalp_bot/runner/run_live_aurora.py`.

---

## 6) Project conventions (узгоджені з SSOT)

* **Config‑driven:** `configs/*.yaml` (не хардкодити). `.env` читає `tools/auroractl.py`.
* **Pre‑trade контракт:** runner → `/pretrade/check` (latency, slippage\_est, p\_tp, e\_pi\_bps, regime, sprt\_llr), service → allow/max\_qty/reasons/cooloff.
* **Expected‑return gate:** `core/scalper/calibrator.py::predict_p(score)` + `e_pi_bps(...)` → allow якщо `E[Pi] > risk.pi_min_bps`.
* **Binance semantics:** `isBuyerMaker=True ⇒ SELL taker`, `False ⇒ BUY`.
* **Events/logging:** тільки структурований JSON через `common/events.py`.

---

## 7) File map (не актуально)

* API `api/service.py` • Runner `skalp_bot/runner/run_live_aurora.py`
* Features `skalp_bot/core/signals.py`, `core/scalper/features.py` • Calibrator `core/scalper/calibrator.py`
* Gates `core/aurora/pretrade.py` • Exchange `skalp_bot/exch/ccxt_binance.py`
* Configs `skalp_bot/configs/default.yaml`, `configs/v4_min.yaml`


---

## 8) Defaults (коли не вистачає даних)

* Таймаути: HTTP 3s, backoff 0.4→6.4s ×5, recvWindow 5000 ms.
* Ротація логів: 50 MB × 5 бекапів. Кодеки Parquet — `snappy` (якщо доступно; інакше JSONL).
* Risk: `daily_dd_limit_pct=10`, `cvar_alpha=0.1`, `spread_bps_limit=80`, `latency_ms_limit=500`.
* Reward: `tp_pct=0.5`, `trail_bps=20`, `breakeven_after_R=0.8`, `max_R=3.0`.
* Заборонено виходити за рамки лот‑/цінових фільтрів біржі; на помилці — нормалізуй коди і **не** дублюй ордери.

---

---

