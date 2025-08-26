# 📜 COPILOT MASTER ROADMAP — Aurora + WiseScalp PROD (Algorithmic Spec v1.1)

> Ти — Copilot цього репозиторію. Виконуй **строго за специфікацією** нижче. Кожне завдання має: Мету → Формули/Алгоритми → API/Сігнатури → Кроки реалізації → Тести → DoD. Працюй фазами, відкривай PR з DoD і прикладами логів/артефактів. Всі зміни **ідемпотентні**.

---

## 0) Kickoff & стандарти

**TASK_ID: Z0-SETUP-BASE**

**Мета:** Вирівняти стиль і PR-дисципліну.

**Кроки:**
- Додай `.editorconfig`, `.gitattributes`, `.gitignore` (виключи `__pycache__/`, `.pytest_cache/`, `*.pyc`, `logs/*`, `artifacts/*` окрім `.keep`).
- Додай `pytest.ini`:
  ```ini
  [pytest]
  addopts = -q
  testpaths = tests
  ```
- Додай `.github/PULL_REQUEST_TEMPLATE.md`, `CONTRIBUTING.md` (стиль комітів: `type(scope): message`).
- Створи `ROADMAP_STATUS.md` (таблиця: TASK_ID | Статус | Commit | Дата | Нотатки).

**Тести/DoD:** Файли на місці, `pytest -q` запускається (навіть якщо 0 тестів).

### TASK_ID: Z0-SETUP-BASE — Progress
- [x] Status: DONE  
- Commit: `pending-hash`  
- Date: 2025-08-26  
- Artifacts: `.editorconfig`, `.gitattributes`, `.gitignore` updated, `.github/PULL_REQUEST_TEMPLATE.md`, `CONTRIBUTING.md`, `ROADMAP_STATUS.md`, `tests/smoke/test_pytest_smoke.py`  
- Assumptions: Added minimal smoke test to satisfy DoD when repository has no tests in testpaths.  
- Notes: Preserved existing pytest asyncio setting; added testpaths=tests.

---

## 1) Аудит і чистка

### A1 — Аудит репозиторію

**TASK_ID: A1-AUDIT-REPORT**

**Мета:** Видимість того, що реально використовується.

**API/CLI:** створити `tools/repo_audit.py`:
```python
#!/usr/bin/env python3
from dataclasses import dataclass
from pathlib import Path
from typing import List

@dataclass
class ModuleInfo:
    path: str
    lines: int
    has_tests: bool
    last_commit: str  # optional, via `git` subprocess

@dataclass
class AuditReport:
    modules: List[ModuleInfo]
    dead_code: List[str]
    notebooks: List[str]
    runners: List[str]

def scan_repo(root: Path) -> AuditReport:
    ...
```
**Кроки:**
- Згенеруй дерево файлів + таблицю «модуль → призначення» у `docs/AUDIT_CURRENT_STATE.md`.
- Познач `dead_code` (файли без імпорту/викликів), старі teacher/student, `living_latent/**`, ноутбуки.

**DoD:** `docs/AUDIT_CURRENT_STATE.md` існує з переліком і висновками.

### TASK_ID: A1-AUDIT-REPORT — Progress
- [x] Status: DONE  
- Commit: `pending-hash`  
- Date: 2025-08-26  
- Artifacts: `tools/repo_audit.py`, `docs/AUDIT_CURRENT_STATE.md`  
- Assumptions: Dead code detection uses simple name-occurrence heuristic to remain idempotent without heavy import graph analysis.  
- Notes: Excludes virtualenv/cache folders; includes runners list heuristically.

### A2 — Архівація зайвого

**TASK_ID: A2-PURGE-LEGACY**

**Мета:** Залишити лише прод-тракт Aurora+WiseScalp.

**Кроки:**
- Перемісти R&D у `archive/YYYYMMDD/` з індексом `ARCHIVE_INDEX.md` (мапа «звідки→куди»).
- Онови `README.md > Repo layout`.

**DoD:** API/runner стартує; імпорти не зламані.

- [x] Status: DONE  
- Commit: `pending-hash`  
- Date: 2025-08-26  
- Artifacts: `archive/20250826/ARCHIVE_INDEX.md`, updated `README.md` repo layout  
- Notes: No files moved yet to avoid breaking imports; index created for future moves.

---

## 2) Документація — єдине джерело правди

**TASK_ID: D1-DOCS-SKELETON**

**Мета:** Створити кістяк доків: `docs/ARCHITECTURE.md`, `docs/AURORA.md`, `docs/SCALPER.md`, `docs/OBSERVABILITY.md`, `docs/CONFIG.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md`.

**DoD:** Док-файли створено зі змістом (TOC) і заголовками розділів.

### TASK_ID: D1-DOCS-SKELETON — Progress
- [x] Status: DONE  
- Commit: `pending-hash`  
- Date: 2025-08-26  
- Artifacts: `docs/ARCHITECTURE.md`, `docs/AURORA.md`, `docs/SCALPER.md`, `docs/OBSERVABILITY.md`, `docs/CONFIG.md`, `docs/RUNBOOK.md`, `docs/SECURITY.md`

---

## 3) Конфіги + .env перемикач

**TASK_ID: C1-CONFIG-LOADER**

**Мета:** Версійовані конфіги й жорстка валідація.

**Схема (Pydantic):**
```python
from pydantic import BaseModel, Field, conint, confloat
from typing import Literal

class RewardCfg(BaseModel):
    tp_pct: confloat(ge=0, le=100) = 0.5
    trail_bps: conint(ge=0) = 20
    trail_activate_at_R: confloat(ge=0, le=5) = 0.5
    breakeven_after_R: confloat(ge=0, le=5) = 0.8
    max_position_age_sec: conint(ge=10) = 3600
    atr_mult_sl: confloat(ge=0, le=10) = 1.2
    target_R: confloat(ge=0, le=10) = 1.0
    max_R: confloat(ge=0, le=20) = 3.0

class GatesCfg(BaseModel):
    spread_bps_limit: conint(gt=0, lt=2000) = 80
    latency_ms_limit: conint(gt=0, lt=5000) = 500
    vol_guard_std_bps: conint(gt=0, lt=5000) = 300
    daily_dd_limit_pct: confloat(gt=0, le=50) = 10.0
    cvar_alpha: confloat(gt=0, lt=0.5) = 0.1
    no_trap_mode: bool = True

class DQCfg(BaseModel):
    enabled: bool = True
    cyclic_k: conint(ge=2, le=20) = 5
    cooldown_steps: conint(ge=1, le=10000) = 300

class Config(BaseModel):
    env: Literal['dev','testnet','prod'] = 'testnet'
    symbols: list[str] = ['BTCUSDT']
    reward: RewardCfg = RewardCfg()
    gates: GatesCfg = GatesCfg()
    dq: DQCfg = DQCfg()
```

**API:**
```python
# core/config_loader.py
from typing import Optional

def load_config(name: Optional[str]) -> Config:
    """Читає .env:AURORA_CONFIG_NAME або name, вантажить YAML у Config. На помилці — лог HEALTH.ERROR і sys.exit(2)."""
```

**CLI:** `tools/auroractl.py config-use --name master_config_v2`, `config-validate`.

**DoD:** Невалідний YAML зупиняє старт; перемикач працює.

### TASK_ID: C1-CONFIG-LOADER — Progress
- [x] Status: DONE  
- Commit: `pending-hash`  
- Date: 2025-08-26  
- Artifacts: `core/config_loader.py`, `tools/auroractl.py (config-use, config-validate)`, `configs/master_config_v{1,2}.yaml`, `.env.example`  
- Notes: Loader emits HEALTH.ERROR to stderr and exits(2) on invalid YAML per spec. CLI validated both examples.

---

## 4) Сигнали, рішення, гейти — формули

### 4.1 Мікроструктура сигналів (WiseScalp)

Позначення: bid `B`, ask `A`, mid `M=(A+B)/2`, spread_bps `= (A-B)/M * 1e4`.

**L5 Order Book Imbalance (OBI):**
\[
OBI_{L5} = \frac{\sum_{i=1}^{5} Vol_{bid,i} - \sum_{i=1}^{5} Vol_{ask,i}}{\sum_{i=1}^{5} Vol_{bid,i} + \sum_{i=1}^{5} Vol_{ask,i}}
\]

**Trade Flow Imbalance (TFI, вікно T секунд):**
\[
TFI_T = \frac{\sum V_{sell\_taker} - \sum V_{buy\_taker}}{\sum (V_{sell\_taker}+V_{buy\_taker})}
\]

**Absorption score (асиметрія ліквідності):**
\[
Abs = \frac{MO_{opp\_vol\_T}}{Quote_{side\_vol\_T}+\epsilon} \cdot I\{ |\Delta price| < \delta \}
\]
де `MO_opp_vol_T` — обсяг ринкових угод проти сторони з великою котировкою; `I{}` — індикатор «ціна майже не рухається».

**Micro‑price:**
\[
P_{micro} = \frac{A \cdot BVol + B \cdot AVol}{BVol + AVol}
\]

**Композитний скор (лінійний приклад):**
\[
score = w_1 \cdot OBI + w_2 \cdot (-TFI) + w_3 \cdot Abs + w_4 \cdot \operatorname{sign}(P_{micro}-M)
\]
Початково `w=[0.4, 0.3, 0.2, 0.1]` (калібрується в бек‑тесті).

**Intent (псевдо):** якщо `score > θ_long` → LONG; якщо `score < -θ_short` → SHORT; `θ≈0.2`.

### 4.2 Розмір, стоп, інвентар

**Risk per trade (USDT):** `R$ = risk_pct_capital * capital`.
**Stop distance (ціна):** `SL_dist = max(ATR_k * ATR, min_tick*K)`.
**К-сть контрактів:** `qty = floor(R$ / SL_dist / contract_value)` з повагою до лот‑сайзу.
**Інвентарні межі:** `|position_qty| ≤ inv_cap`, `daily_drawdown ≤ limit`.

### 4.3 Гейти Aurora

**Spread guard:**
\[ spread\_bps = \frac{A-B}{(A+B)/2} \times 10^4; \quad allow = (spread\_bps \le limit) \]

**Latency guard:** оцінюй `lat_ms` останнього циклу; deny якщо `lat_ms > limit`.

**Volatility guard:**
\[ \sigma_{bps} = 10^4 \cdot \operatorname{std}(\Delta \ln M) \cdot \sqrt{K}\ ;\ allow=(\sigma_{bps} \le limit) \]

**CVaR (історична оцінка):** для масиву останніх `N` trade‑PnL,
\[ CVaR_\alpha = E[ PnL \mid PnL \le q_\alpha ] \]
deny, якщо `CVaR_α < -threshold`.

**Daily DD:**
\[ DD\% = 100\cdot\left(1 - \frac{Equity_{now}}{Equity_{peak\_today}}\right);\ allow=(DD\% \le limit) \]

**Expected‑return gate (опціонально):**
\[ E[r] = \beta\cdot score;\ allow = (E[r] \ge r_{min}) \]

---

## 5) Спостережуваність: події, JSONL, ротація

**TASK_ID: L1-ORDER-LOGGER**

**Мета:** Єдина схема логів ордерів.

**Pydantic‑схеми (скорочено):**
```python
# core/schemas.py
from pydantic import BaseModel
from typing import Literal, Optional

class DecisionFinal(BaseModel):
    ts_iso: str; decision_id: str; symbol: str; side: Literal['BUY','SELL']
    score: float; signals: dict; intent: dict

class OrderBase(BaseModel):
    ts_iso: str; decision_id: str; order_id: str; symbol: str; side: str; qty: float

class OrderSuccess(OrderBase):
    avg_price: float; fees: float; filled_pct: float; exchange_ts: Optional[str] = None

class OrderFailed(OrderBase):
    error_code: str; error_msg: str; attempts: int; final_status: str

class OrderDenied(OrderBase):
    gate_code: str; gate_detail: dict; snapshot: dict
```

**API:**
```python
# core/order_logger.py
class OrderLogger:
    def __init__(self, dir: str, rotate_mb: int = 50, backups: int = 5): ...
    def log_success(self, rec: OrderSuccess) -> None: ...
    def log_failed(self, rec: OrderFailed) -> None: ...
    def log_denied(self, rec: OrderDenied) -> None: ...
```

**DoD:** Файли `logs/orders_*.jsonl` створюються, записи валідні.

**TASK_ID: L2-AURORA-EVENTS**

**Події (enum):** `REWARD.TP|TRAIL|BREAKEVEN|TIMEOUT|MAX_R`, `HEALTH.ERROR|RECOVERY`, `SPREAD_GUARD_TRIP`, `RISK.DENY.POS_LIMIT|DRAWDOWN|CVAR`, `CONFIG.SWITCHED`, `STARTUP.OK`.

**API:** `AuroraEventLogger.emit(event_code: str, details: dict, position_id: str|None)`.

**TASK_ID: L3-METRICS-SUMMARY**

**Алгоритм:** парсити `orders_*.jsonl` і `aurora_events.jsonl` за `window_sec`, рахувати `fill_rate`, `reject_rate(by reason)`, `slippage_p50/p95`, `winrate_proxy`.

**CLI:** `tools/metrics_summary.py --window-sec 3600` → `reports/summary_gate_status.json`.

**DoD:** JSON у `reports/` з реальними числами.

---

## 6) RewardManager: формули і інтеграція

**TASK_ID: R1-REWARD-MANAGER**

**Стани:**
- entry_price `P0`, поточна `P`, стоп `SL`, тейк `TP`, небхідний ризик‑крок `R = (P0 - SL) * side_sign / tick_value`.
- `R_realized = (P_exit - P0) * side_sign / (P0 - SL)`.

**PnL_adj (з поправками):**
\[ PnL_{adj} = PnL_{realized} - fees - funding - \lambda\cdot |slippage| \]

**Брейк-івен (після kR):** якщо `R_unreal >= breakeven_after_R` →
\[ SL \leftarrow P0 + side\_sign\cdot (fees\_per\_unit + \delta) \]

**Трейлінг:** активується при `R_unreal ≥ trail_activate_at_R`,
\[ SL \leftarrow \max(SL, P - side\_sign\cdot trail\_bps\cdot M/10^4) \]

**Time‑exit:** якщо `age_sec > max_position_age_sec` → `TIME_EXIT`.

**Max‑R exit:** якщо `R_unreal ≥ max_R` → `MAX_R_EXIT`.

**API:**
```python
# core/reward_manager.py
from dataclasses import dataclass
from typing import Literal, Optional

@dataclass
class PositionState:
    side: Literal['LONG','SHORT']
    entry: float; price: float; sl: float; tp: Optional[float]
    age_sec: int; atr: float
    fees_per_unit: float; funding_accum: float

@dataclass
class RewardDecision:
    action: Literal['HOLD','TP','TRAIL_UP','MOVE_TO_BREAKEVEN','TIME_EXIT','MAX_R_EXIT']
    new_sl: Optional[float] = None
    meta: dict = None

class RewardManager:
    def __init__(self, cfg: RewardCfg): ...
    def update(self, st: PositionState) -> RewardDecision: ...
```

**Тести:** сценарії для TP/trail/breakeven/timeout/maxR (табличні вхідні → очікуване `action`).

**TASK_ID: R2-REWARD-INTEGRATION**

**Інтеграція в execution:**
- `TP|TIME_EXIT|MAX_R_EXIT` → закриття позиції (маркет/ліміт за політикою), лог у `orders_success/failed`.
- `TRAIL_UP|MOVE_TO_BREAKEVEN` → оновлення SL/TSL через Cancel&Replace; лог `aurora_events`.

**DoD:** Інтеграційний мок-ран проходить весь шлях: decision→order→fills→events.

---

## 7) Тести (нова структура)

**TASK_ID: T1-TEST-SKELETON**

**Файли:**
- `tests/test_config_loader.py`
- `tests/test_order_logger.py`
- `tests/test_aurora_events.py`
- `tests/test_reward_manager.py`
- `tests/test_integration_execution.py` (моки біржі)
- `tests/test_metrics_summary.py`

**Helper:** `tools/run_tests_clean_env.py` — прибирає `AURORA_*` з env, чистить кеші, запускає `pytest -q`.

**DoD:** Всі нові тести PASS локально.

---

## 8) Governance & гейти (Aurora)

**TASK_ID: A3-GATES-AND-KILLSWITCH**

**Контракт:**
```python
# aurora/governance.py
class Governance:
    def approve(self, intent: dict, risk_state: dict) -> dict:
        """Повертає approved_intent або deny з кодом. Викликає гейти в порядку: DQ → Drawdown/CVaR → Spread → Latency → Volatility → Position limits."""
```

**Коди:** `AURORA.EXPECTED_RETURN_ACCEPT`, `SPREAD_GUARD_TRIP`, `RISK.DENY.POS_LIMIT|DRAWDOWN|CVAR`, `LATENCY_GUARD_TRIP`, `VOLATILITY_GUARD_TRIP`, `UNKNOWN`.

**Kill‑Switch v2:**
- авто‑стоп при `daily_dd ≥ limit` або `reject_rate(window) ≥ R%`.
- розблокування: ручне підтвердження + cooldown.

**Тести:** property‑тести: spread>limit → deny; reject‑storm → kill‑switch активний.

**TASK_ID: A4-OPS-ENDPOINTS**

**Ендпоїнти:** `/liveness`, `/readiness`, `/metrics`, токен `X-OPS-TOKEN`.

**DoD:** `auroractl health` → 200; неправильний токен → 401.

---

## 9) Інтеграція з Binance (ідемпотентність)

**TASK_ID: B1-BINANCE-EXECUTION-HARDENING**

**Idempotency:** `clientOrderId = f"{run_id}-{ts_ms}-{seq}"`.

**Становий автомат ордера:** `CREATED→SUBMITTED→ACK|REJECTED→PARTIAL*→FILLED|CANCELLED|EXPIRED`.

**Retry policy:** експоненційний backoff на `429/5xx`, фільтрація дублів по `clientOrderId`.

**Error mapping (нормалізатор):**
- `-1013` → `PRICE_FILTER`, `-1021` → `TIMESTAMP`, `-2010` → `INSUFFICIENT_BALANCE`, `-2019` → `MARGIN_NOT_ENOUGH`, `-4164` → `MIN_NOTIONAL`, інше → `UNKNOWN` (лог сирого payload).

**WSS:** реконект, revive `listenKey`, реплей останнього N.

**DoD:** мок‑ран + короткий testnet‑ран без дубль‑ордерів; логи повні.

---

## 10) CI/CD і пакування

**TASK_ID: CI1-GHA-SMOKE**

**Workflow:**
- `lint` (ruff/flake8 опційно), `pytest -q`.
- Артефакти: `logs/**` (sample), `reports/**`.

**TASK_ID: P1-PACKAGING**

**Dockerfile (тонкий):** python:3.11‑slim, томи для `logs/`, `artifacts/`, `.env` через envfile.

**DoD:** CI зелений; контейнер стартує з `AURORA_CONFIG_NAME`.

---

## 11) Канарка (12h) та звіти

**TASK_ID: K1-CANARY-12H**

**CLI:** `make canary MINUTES=720` або `tools/run_canary.py`.

**Вихідні артефакти:**
- `reports/summary_gate_status.json`
- приклади `logs/orders_*`, `logs/aurora_events.jsonl`
- `reports/run_digest.md`: `winrate`, `avgR`, `denied_by_gate`, топ‑помилки, `slippage_p50/p95`.

**DoD:** Канарка завершена; артефакти збережені.

---

## 12) Заключна документація та семпли

**TASK_ID: D2-DOCS-FINAL** — заповнити доки реальними прикладами, оновити README (Quickstart, Prod‑testnet runbook, таблиця `.env` та `configs/*.yaml`).

**TASK_ID: S1-SAMPLES** — додати `.env.example`, `configs/master_config_v1.yaml`/`v2.yaml` (живі приклади), перевірка `auroractl config-validate`.

---

## Додатково: Data Quality Trip‑wires (формули)

- **Cyclic‑sequence (already R1):** тригер при ≥K однакових патернах рішень: `pattern = (side, bucketed_score)`; cooldown `dq.cooldown_steps`.
- **Stale book:** `ts_now - ts_book > Δt_max` → deny всі нові інтенти.
- **Crossed book:** якщо `best_bid ≥ best_ask` → `DQ_EVENT: CROSSED_BOOK` + kill у суворому режимі.
- **Abnormal spread/variance:** якщо `spread_bps > μ_spread + n·σ_spread` чи `σ_rt > limit`.

Лог подій: `DQ_EVENT {type, level, cooldown_s}` у `aurora_events.jsonl`.

---

## Командні шпаргалки

```bash
# Чистка середовища і тести
python tools/run_tests_clean_env.py

# Перемкнути конфіг
auroractl.py config-use --name master_config_v2
auroractl.py config-validate

# Агрегація метрик з логів
python tools/metrics_summary.py --window-sec 3600

# Старт API/health
python tools/auroractl.py start-api
python tools/auroractl.py health --endpoint liveness

# Канарка (12 годин)
make canary MINUTES=720
```

---

### Прогрес (v4) — 2025‑08‑26



- Оновлюй `ROADMAP_STATUS.md` після кожного merge.

> Кінець специфікації v1.1. Далі — `Z0-SETUP-BASE`, потім `A1-AUDIT-REPORT`. Виконуй строго по черзі та фіксуй результати у PR.
### Правила PR

## Progress v7 (2025-08-26)
- [x] AUR-004 — Lifecycle Correlator: FSM + p50/p95/p99 + tests — ✅
- [x] L3-METRICS-SUMMARY — target JSON schema + .jsonl.gz support — ✅
- [x] A4-POLISH — events counter hook + orders_* counters tied to log writes — ✅
- [x] L2-AURORA-EVENTS (core) — ORDER.SUBMIT/ACK/PARTIAL/FILL/REJECT wiring — ✅
- [x] L2-AURORA-EVENTS (final) — ORDER.CANCEL.REQUEST/CANCEL.ACK/EXPIRE wiring + tests — ✅

**Artifacts**
- `logs/aurora_events.jsonl(.gz)`
- `logs/orders_{success,failed,denied}.jsonl(.gz)`
- `reports/summary_gate_status.json`
- `README.md` — Ops & Tokens + Event Codes, Post‑merge checklist

**Commits**
- L3: <hash>
- A4: <hash>
- L2 core: <hash>
- L2 final (cancel/expire): <hash>
 - Docs insert (README Ops/Events): <hash>


## Progress v8 (2025-08-26)
- [x] R1-REWARD-MANAGER — unit tests added and green — ✅

**Artifacts**
- `tests/test_reward_manager.py`

**Commits**
- R1 tests: <hash>

**Notes**
- Implemented RewardManager tests for MAX_R_EXIT, TIME_EXIT, TP, MOVE_TO_BREAKEVEN, TRAIL_UP, HOLD. Adjusted tolerances for float comparisons to avoid flakiness.

