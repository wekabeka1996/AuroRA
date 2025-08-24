# Aurora × OBI‑Scalper — Implementation Spec v1.1 (handoff)

**TASK\_ID:** AURORA-SCALPER-SPEC-V1.1
**Owner:** Мудрець (архітектор)
**Audience:** LLM/квант-команди, інженери інтеграції
**Status:** Ready for implementation / shadow
**Scope:** Chat‑інтеграція Аврори + мікроструктурний скальп‑ядро (OBI/TFI/Absorb/MicroPrice) з калібруванням, гейтами й тестами.

---

## 0) Changelog v1.1

* ✅ Виправлено семантику **TFI на Binance** (`isBuyerMaker=True → market sell`)
* ➕ Додано **калібрування score→P(TP)** (ізотоніка/Platt) + **очікувана дохідність** з fee+slippage
* ➕ **SPRT/байєсівська послідовна перевірка** для реконфірму входу (≤500мс)
* ➕ **TRAP/fake walls** як метрика cancel vs replenish (L1..L5, 1–3s)
* ➕ **Latency‑guard** (p95 циклу) та **slippage‑guard** (“liquidity ahead”)
* ➕ **Адаптивні ваги** α‑скора за режимами (`rv_1m`, `spread_bps`)
* ➕ **Toxicity‑filter** (realized vs effective spread)
* 🛠 ATR warm‑up: проксі через `rv_1m_bps` перші 15 хв або pre‑seed з історії
* 🧰 Розширені тести T‑07…T‑14, оновлений DoD

---

## 1) System Overview

**Ролі:**

* **Chat Orchestrator**: slash‑команди, алерти, статус
* **Aurora (watchdog)**: pre‑trade gate, ескалації (cooloff/halt/kill), ризик‑ліміти
* **Policy Shim V2**: нормалізація стейту, рішення `NO_OP|EXECUTE|COOL_OFF`
* **OBI‑Scalper Core**: α‑скор, калібратор, SPRT, входи/виходи, OCO
* **Runner/ExecutionCore**: ордери/маршрутизація

**Event Bus:** JSONL `logs/events.jsonl` (single writer per service, idempotent append)

---

## 2) Data & Features (stream)

* **LOB L1/L5**: цiна/обсяг, глибина на 5 рівнях; **OBI\_L**
* **Trades feed**: `price, size, isBuyerMaker`
  **Binance semantics:** `isBuyerMaker=True ⇒ SELL агресор`, `False ⇒ BUY агресор`.
  **TFI\_W**: нормалізований дисбаланс ринкових покупок/продажів
* **Micro‑price (P\_micro)**, **Absorption**, **OFI (Cont‑style)**
* **Volatility**: `rv_1m_bps`, `ATR(14)` (Wilder) with warm‑up policy
* **TrendAlign**: нормалізований добуток похідних `EMA_{15s}` та `EMA_{60s}`

**Робаст‑нормалізація:**
`x̂ = clip( 2*(x − p50)/(p95 − p05), −1, 1 )` на ковзному вікні (\~600 тiків), P²/TDigest у стрімі.

---

## 3) Alpha Score & Calibration

**Базовий α‑скор (стартові ваги):**
`score = 0.30·ÔBI + 0.25·T̂FI + 0.15·ÂBSORB + 0.15·M̂Bias + 0.10·ÔFI + 0.05·TrendAlign`
Штраф консенсусу: якщо `sign(OBI) ≠ sign(TFI)` → `score *= 0.5` (раніше −0.08 було недостатньо).
Компресія OBI: `ÔBI = tanh(c·OBI)`, `c` підбирається валід.

**Режими ринку R ∈ {tight, normal, loose}:** за терцилями `rv_1m_bps, spread_bps`.
Для кожного R окремий вектор ваг `w_R` (walk‑forward, L2‑регуляризація, |w\_i|≤0.6). Онлайн‑адаптація: `w_t=(1−λ)w_{t−1}+λ·ŵ`.

**Калібрування score →  p̂ = P(TP before SL | features):**

* Ізотонічна регресія (moнотонність) або Platt (логістика)
* Під час shadow логувати: `score, p̂, a, b, fees_bps, slip_bps(q), E[Π]`

**Очікувана дохідність (bps):**
`E[Π] = p̂·b − (1−p̂)·a − (fees_bps + slip_bps(q))`
Вхід дозволено якщо `E[Π] > π_min` (напр. π\_min = 0.2·ATR\_bps або p75 шуму).

**Slippage‑model (“liquidity ahead”):**
`slip_bps(q) ≈ (10^4/mid) * (1/q) * Σ_{j=1..J(q)} Δp_j * min{q, depth@level_j}`; guard: `slip_bps(q) ≤ η·b` (η≈0.3).

---

## 4) Entry Validation (Gates)

1. **Clock‑gate** (сесійні вікна; старт зі статичних)
2. **Spread‑gate**: `spread_bps ≤ min(12, 4 + 0.3·rv_1m_bps)`
3. **Consensus**: `|ÔBI|≥0.20` & `|T̂FI|≥0.10` & `sign` узгоджені
4. **Persistence**: ≥ 2–3 послідовні перевірки (≤300–500мс total)
5. **TRAP‑guard** (див. §5)
6. **ATR‑ready** або warm‑up через `rv_1m_bps·κ` перші 15 хв
7. **Latency‑guard**: `p95(loop_latency_ms) ≤ L_max` (старт: 50мс; warn>50, block>100)
8. **Vol‑of‑vol guard**: `Δrv_1m > p95(60s)` → skip
9. **Toxicity‑filter**: `tox = |realized_spread − effective_spread| / quoted_spread`; якщо `tox>0.5` → block

**SPRT/Байєс‑реконфірм (≤500мс):**
Акумулюємо `LLR_t` по коротким підспостереженням (score або Δp):
вхід при `LLR_t ≥ A`, відмова при `LLR_t ≤ B`, A/B з бажаних (α,β).

---

## 5) TRAP / Fake‑Walls Metric

На вікні 1–3s, рівні L=5:

* `ReplRate = Σ max(Δadd_i,0)/Δt`, `CancelRate = Σ max(Δcancel_i,0)/Δt`
* `TrapScore = z( CancelRate − ReplRate ) · sign(OBI)`
* TRAP‑flag=1, якщо:

  * `TrapScore > τ_trap` **або**
  * `sign(OBI) ≠ sign(TFI)` **і** `CancelRate ≥ p90`

Пороги адаптивні (ковзні перцентилі за 5 хв). Початкові: `τ_trap = p90`.

---

## 6) Exits & Position Sizing

**OCO:** TP = `+1.2·ATR`, SL = `−0.8·ATR` (R/R≈1.5).
**Time‑stop:** адаптивний: `time_stop_s = clip(60*(1+log(rv_1m_bps/10)), 30, 120)`
**Reversal exit:** `score` змінює знак і утримує 2–3 тики.
**Trailing:** при `UPnL > 0.5·ATR` → трeйлити SL на `0.5·ATR`.

**Sizing:**
`q = q0 · Aurora.risk_scale · g(OBI_persist)`; Kelly‑кеп: `f = κ·f*`, `f* = (p̂·b − (1−p̂)·a)/(a·b)`, `κ∈[0.1,0.3]`.
Guard: `slip_bps(q) ≤ η·b`.

---

## 7) Aurora Integration

**Політика ескалацій:** warn → cooloff(N) → halt(15m) → kill‑switch (manual reset).
**Ліміти (дефолт):** `dd_day_limit_pct=4.0`, `inventory_cap_usdt=40`, `latency_guard_ms=250`, `cooloff_base_sec=120`.

**Pre‑trade check payload (доповнений):**

```json
{
  "slip_bps_est": 5.2,
  "p_tp": 0.58,
  "e_pi_bps": 3.7,
  "latency_ms": 34,
  "mode_regime": "normal",
  "sprt_llr": 2.1
}
```

**Команди в чаті:**

* `/aurora status` | `/aurora arm` | `/aurora disarm`
* `/risk set dd_day 3.5%` | `/ops cooloff 5m` | `/ops reset`
* `/logs tail 50`

---

## 8) Event Taxonomy & Schemas

**Типи:**

* `POLICY.DECISION.{NO_OP|EXECUTE|COOL_OFF}`
* `AURORA.{NO_OP_STREAK|COOLOFF_{START,END}|RISK_WARN|HALT|KILL_SWITCH}`
* `EXEC.{ORDER_PLACED|ORDER_FILLED|ORDER_CANCELLED}`
* `HEALTH.{LATENCY_HIGH|HEARTBEAT_MISSED}`

**Приклади:**

```json
{"type":"policy.decision","ts":"2025-08-24T06:10:00Z","payload":{"decision":"NO_OP","prefer":0,"confidence":0.62,"reasons":["low edge","spread widened"]}}

{"type":"aurora.alert","severity":"critical","code":"AURORA.KILL_SWITCH","message":"Daily DD limit breached (>=4.0%) → ALL HALTED","context":{"dd_day_pct":4.2}}
```

---

## 9) Config (v4‑min)

```yaml
aurora:
  enabled: true
  dd_day_limit_pct: 4.0
  inventory_cap_usdt: 40
  latency_guard_ms: 250
  cooloff_base_sec: 120
policy_shim:
  no_op_streak_to_cooloff: 2
  action_ratio_floor_10m: 0.08
  prefer_bias_weight: 1.0
chat:
  commands_enabled: true
logging:
  path: logs/events.jsonl
  level: INFO
```

---

## 10) State Machine

`IDLE → PRECHECK → (GATES) → SPRT → OPEN → (TP|SL|TIME|REVERSAL|FORCED_EXIT) → IDLE`
У `OPEN` перевіряти `aurora.allow` кожні 5s; при `halt/kill` — форсований вихід.

---

## 11) Testing Strategy

### Unit / Property

* Нормалізація ∈\[−1,1], монотонність calibrator, без `look‑ahead`
* ATR streaming з гепами; OBI/TFI інваріанти LOB‑мас
* TFI Binance semantics (golden cases)

### Integration (розширено)

* **T‑01** NO\_OP→COOL\_OFF (streak≥2)
* **T‑02** DD breach → KILL\_SWITCH
* **T‑03** LATENCY\_GUARD (p95>threshold)
* **T‑04** ACTION\_RATIO\_FLOOR → COOL\_OFF(180s)
* **T‑05** Slash‑команди (status/set/cooloff/reset)
* **T‑06** Resume after cooldown
* **T‑07** Calibrator monotonic + `E[Π]>π_min` → допускає вхід
* **T‑08** Slippage‑guard блокує при `slip_bps(q)>η·b`
* **T‑09** SPRT: `LLR≥A` → вхід; `LLR≤B` → відмова
* **T‑10** TRAP: high cancel rate p≥90 → блок
* **T‑11** Toxicity>0.5 → блок; ≤0.5 → не блокує
* **T‑12** ATR warm‑up: перші 15 хв — проксі через `rv_1m_bps`
* **T‑13** Reversal exit тригериться при зміні знаку скoра (2–3 тики)
* **T‑14** Fail‑closed: pretrade timeout/observability<τ → BLOCK

### Offline Replay / Shadow

* ROC/PR, **WinRate by clock window**, **PnL by vol bins**, **Slippage vs OBI**
* DRO‑adj ≥ 0.6; Sharpe>1.5 на shadow (14 днів)

---

## 12) Monitoring (Dashboards)

* `WinRate by clock window`
* `Avg slippage (bps) by |ÔBI| bins`
* `Fill rate vs score threshold`
* `Aurora rejection reasons (pie)`
* `Latency p95, p99`
* `DD_day, inventory utilization`

---

## 13) Security & Prod Modes

* **Prod = fail‑closed** (будь‑яка невизначеність → BLOCK)
* Обмеження прав Runner (ордери лише в дозволених символах/лініях)
* Rate‑limits на команди; audit‑trail для `/ops reset`

---

## 14) Handoff: Work Packages (LLM‑tickets)

**WP‑A Calibrator**
Inputs: `score, a, b, fees_bps, slip_bps(q)` → Output: `p̂, E[Π]`.
DoD: монотонність, unit‑тести, T‑07 зелений, shadow‑метрики логуються.

**WP‑B SPRT Module**
Inputs: короткі підспостереження (score/Δp) → Output: `LLR`, enter/deny.
DoD: контроль (α,β), T‑09 зелений, latency ≤500мс.

**WP‑C TRAP Detector**
Inputs: L1..L5 adds/cancels/trades (1–3s) → Output: `TrapFlag/TrapScore`.
DoD: перцентильні пороги, T‑10 зелений.

**WP‑D Latency & Slippage Guards**
DoD: T‑03/T‑08 зелені, дашборд p95/p99, конфіг порогів.

**WP‑E Toxicity Filter**
DoD: формула, thresholds, T‑11 зелений.

**WP‑F Adaptive Weights**
DoD: 3 режими, таблиця `w_R`, валідація на реплеях; toggle‑флаг.

**WP‑G Binance TFI Semantics**
DoD: unit golden‑tests, перевірка `isBuyerMaker` логіки, T‑XX pass.

**WP‑H Chat & Aurora**
DoD: Slash‑команди, події, T‑01..T‑06, sticky‑critical алерти.

---

## 15) Output Formats

* **Events:** JSONL (приклади в §8)
* **Chat replies:** JSON/markdown з ключовими полями (`status`, `reasons`, `next_check_ts`)
* **Artifacts:** `docs/aurora_chat_spec_v1.1.md`, `tests/integration/test_*.py`, `configs/v4_min.yaml`

---

## 16) Fallback & Error Policy

* Pretrade timeout / observability<τ → `AURORA.HALT` + чат‑alert
* Parsing/config error → `AURORA.HALT` + інструкція `/ops reset`
* Kill‑switch: ручний `/ops reset` з підтвердженням у чаті

---

## 17) Definition of Ready / Done

**DoR:** дані L1/L5+trades доступні; лог‑шлях writable; конфіг v4‑min валідний; чат‑команди доступні.
**DoD:** WP‑A…WP‑H виконані; T‑01…T‑14 зелені; shadow‑період ≥14 днів, Sharpe>1.5; док‑спека в репо, дашборди активні.

---

## 18) Quick References (formulas)

* `E[Π] = p̂·b − (1−p̂)·a − (fees+slip)`
* `slip_bps(q)` через depth consumption (див. §3)
* `TrapScore = z(Cancel − Repl)·sign(OBI)`
* `time_stop_s = clip(60*(1+log(rv_1m_bps/10)), 30, 120)`
* Kelly‑кеп: `f = κ·(p̂·b − (1−p̂)·a)/(a·b)`

---

## 19) Acceptance Checklist (1‑page)

* [ ] Binance TFI semantics виправлені
* [ ] Calibrator монотонний; `E[Π]` логуються
* [ ] Guards (latency/slippage/toxicity/TRAP) активні
* [ ] SPRT ≤500мс, (α,β) підтверджені
* [ ] Adaptive weights (3 режими) зафіксовані в конфігу
* [ ] Slash‑команди працюють; kill‑switch manual reset
* [ ] Інтеграційні тести T‑01..T‑14 green
* [ ] Shadow‑метрики OK; DoD виконано

---

**Примітка:** Продакшн‑режим лише `fail‑closed`. Будь‑які невизначеності або деградація спостережності → BLOCK до ручного `/ops reset`.

---

# 20) Work Breakdown & Copilot Task Cards (Ready-to-use)

> **Формат:** ідемпотентні картки для GitHub Issues / Copilot. Кожна картка має: **TASK\_ID, Inputs, Checkpoints, Output Format, Fallback, Acceptance**. Всі шляхи відносно кореня репо.

## 20.1 Загальні конвенції

* **Мова/версія:** Python ≥3.10
* **Стиль:** ruff/black, типи `typing`, докстрінги NumPy-style
* **Логи:** JSONL через `structlog` у `logs/events.jsonl`
* **Тести:** `pytest -q`; фікстури у `tests/fixtures/`
* **Гілки:** `feature/<TASK_ID>`, PR з чеклістом Acceptance
* **Коміти:** Conventional Commits (`feat:`, `fix:`, `test:`…)
* **CI (опц.):** GitHub Actions: `python -m pip install -e .[dev] && pytest`

## 20.2 Структура репо (додати/уточнити)

```
core/
  aurora/                # watchdog + gates + escalations
    __init__.py
    policy.py            # ескалації, cooloff/halt/kill
    pretrade.py          # pre-trade contract & checks
  scalper/
    __init__.py
    features.py          # OBI/TFI/OFI/MicroPrice/Absorb/TrendAlign
    score.py             # alpha score + adaptive weights
    calibrator.py        # isotonic/platt + E[Pi]
    sprt.py              # sequential test (Wald/Bayes)
    trap.py              # cancel/replenish metrics
    sizing.py            # Kelly-cap & risk_scale integration
    exits.py             # OCO/Time/Trailing/Reversal
  runner/
    __init__.py
    execution.py         # place/cancel orders, allow-list
  chat/
    __init__.py
    commands.py          # /aurora, /risk, /ops, /logs
common/
  __init__.py
  config.py              # pydantic v4-min
  events.py              # event schemas & emitters
  utils.py
configs/
  v4_min.yaml
docs/
  aurora_chat_spec_v1.1.md
tests/
  unit/
  integration/
  fixtures/
logs/
```

---

## 20.3 Copilot Task Cards (WP-A…WP-H)

### 🅰️ WP-A — Calibrator (score→p̂, E\[Π])

**TASK\_ID:** AURORA-CALIBRATOR-A1

**Goal:** Перетворити `score` + контекст у калібровану ймовірність `p̂= P(TP before SL)` і розрахувати очікувану дохідність `E[Π]` (bps), логувати на ENTRY/EXIT.

**Inputs:** `score: float ∈[-1,1]`, `a,b` (ATR-кратності/ bps), `fees_bps: float`, `slip_bps(q): float`, `mode_regime: str`.

**Files:** `core/scalper/calibrator.py`, `tests/unit/test_calibrator.py`.

**API (створити):**

```python
@dataclass
class CalibInput:
    score: float
    a_bps: float
    b_bps: float
    fees_bps: float
    slip_bps: float
    regime: str

@dataclass
class CalibOutput:
    p_tp: float
    e_pi_bps: float

class Calibrator(Protocol):
    def fit(self, scores: NDArray[np.float64], y: NDArray[np.int_]) -> None: ...
    def predict_p(self, score: float) -> float: ...
    def e_pi_bps(self, ci: CalibInput) -> CalibOutput: ...
```

**Steps (Copilot):**

1. Реалізуй `IsotonicCalibrator` (залежність: `scikit-learn`**\[calibration]** або власна ізотоніка). Фолбек — Platt.
2. Додай `e_pi_bps()` = `p*b − (1−p)*a − (fees+slip)`.
3. Логи: `"calibrator.entry": {score,p_tp,e_pi_bps,a,b,fees,slip,regime}`.

**Checkpoints:** C1 клас і тести; C2 монотонність; C3 edge‑cases (`a=0|b=0`, clip p∈\[0,1]).

**Output Format:** `CalibOutput` + JSONL подія.

**Fallback:** якщо калібратор не готовий → `p̂ = sigmoid(k*score)` з `k=2.0`.

**Acceptance:** `tests/unit/test_calibrator.py::test_monotonic`, `::test_e_pi_math` зелені; інтеграція в pre-trade (T‑07).

---

### 🅱️ WP-B — SPRT Module

**TASK\_ID:** AURORA-SPRT-B1

**Goal:** Послідовна перевірка рішення перед входом за ≤500мс.

**Files:** `core/scalper/sprt.py`, `tests/unit/test_sprt.py`, `tests/integration/test_sprt_gate.py`.

**API:**

```python
@dataclass
class SprtConfig:
    mu0: float  # null drift
    mu1: float  # alt drift
    sigma: float
    A: float    # upper threshold
    B: float    # lower threshold (negative)
    max_obs: int

class SPRT:
    def update(self, x: float) -> Literal["CONTINUE","ACCEPT","REJECT"]: ...
    def reset(self) -> None: ...
```

**Steps:** імплементувати LLR акумуляцію для нормального випадку; варіант: байєс‑логіт при невідомій σ.

**Checkpoints:** C1 математика LLR; C2 пороги `A,B` з (α,β); C3 max\_obs.

**Acceptance:** юніт‑тести; інтеграція в gates (T‑09).

---

### 🅲 WP-C — TRAP Detector

**TASK\_ID:** AURORA-TRAP-C1

**Goal:** Детект «fake walls» за cancel vs replenish на L1..L5 (1–3s), адаптивні пороги.

**Files:** `core/scalper/trap.py`, `tests/unit/test_trap.py`, `tests/integration/test_trap_gate.py`.

**API:**

```python
@dataclass
class TrapMetrics:
    repl_rate: float
    cancel_rate: float
    trap_score: float
    trap_flag: bool

def compute_trap(depth_before, depth_after, dt_s: float, obi_sign: int, tfi_sign: int, pctl_thresholds: Mapping[str,float]) -> TrapMetrics: ...
```

**Steps:** реалізувати підрахунок Δadds/Δcancels; z‑score; умови з спеки (TrapScore>τ або cancel p≥90 & sign conflict).

**Acceptance:** T‑10 зелений.

---

### 🅳 WP-D — Latency & Slippage Guards

**TASK\_ID:** AURORA-GUARDS-D1

**Goal:** Блокувати вхід при деградації p95 циклу або при `slip_bps(q) > η·b`.

**Files:** `core/aurora/pretrade.py`, `core/scalper/score.py` (hook), `tests/integration/test_guards.py`.

**API (pretrade доповнити):**

```python
@dataclass
class PretradeReport:
    slip_bps_est: float
    latency_ms: float
    mode_regime: str
    reasons: list[str]
```

**Acceptance:** T‑03, T‑08 зелені; логи HEALTH.LATENCY\_HIGH.

---

### 🅴 WP-E — Toxicity Filter

**TASK\_ID:** AURORA-TOXICITY-E1

**Goal:** Обчислювати `tox = |realized_spread - effective_spread| / quoted_spread` і блокувати при `>0.5`.

**Files:** `core/scalper/features.py`, `tests/unit/test_toxicity.py`.

**Acceptance:** T‑11 зелений; метрика логуються у pre-trade.

---

### 🅵 WP-F — Adaptive Weights by Regime

**TASK\_ID:** AURORA-WEIGHTS-F1

**Goal:** 3 режими ринку (tight/normal/loose) з окремими вагами `w_R` та онлайн‑адаптацією.

**Files:** `core/scalper/score.py`, `configs/v4_min.yaml`, `tests/unit/test_adaptive_weights.py`.

**API:**

```python
class AlphaScorer:
    def score(self, feats: Mapping[str,float], regime: str) -> float: ...
    def set_weights(self, regime: str, w: Mapping[str,float]) -> None: ...
```

**Acceptance:** детермінізм на мок‑фічах; PR має таблицю ваг; інтеграційний smoke з трьома режимами.

---

### 🅶 WP-G — Binance TFI Semantics

**TASK\_ID:** AURORA-BINANCE-G1

**Goal:** Виправити/зафіксувати трактування `isBuyerMaker`.

**Files:** `core/scalper/features.py`, `tests/unit/test_binance_tfi.py`, `tests/fixtures/trades_binance.json`.

**Steps:**

* `isBuyerMaker=True ⇒ market sell`, `False ⇒ market buy`.
* Додати golden‑тести на агрегацію вікон 1s/5s/30s.

**Acceptance:** тести зелені; лінтер/тайпінг ОК.

---

### 🅷 WP-H — Chat & Aurora Commands

**TASK\_ID:** AURORA-CHAT-H1

**Goal:** Реалізувати `/aurora status|arm|disarm`, `/risk set dd_day`, `/ops cooloff|reset`, `/logs tail`.

**Files:** `core/aurora/policy.py`, `core/aurora/pretrade.py`, `core/chat/commands.py`, `tests/integration/test_chat_commands.py`.

**API (commands):**

```python
def cmd_aurora_status() -> dict: ...
def cmd_aurora_arm(flag: bool) -> dict: ...
def cmd_risk_set_dd_day(pct: float) -> dict: ...
def cmd_ops_cooloff(seconds: int) -> dict: ...
def cmd_ops_reset(confirm: bool) -> dict: ...
```

**Acceptance:** T‑01..T‑06 зелені; critical алерти — sticky у чат‑UI (мок).

---

## 20.4 Спільні типи та події (додати)

**`common/events.py` — емітери:**

```python
class EventEmitter:
    def emit(self, type: str, payload: Mapping[str, Any], severity: str | None = None, code: str | None = None) -> None: ...
```

**Словник кодів:** з §8 спеки (POLICY.*, AURORA.*, EXEC.*, HEALTH.*).

---

## 20.5 Конфіг (v4‑min) + Pydantic

**`common/config.py`**: моделі лише з полями з §9; заборонити додаткові.

Тест: `tests/unit/test_config_min.py` (перевірка відхилення кастомних полів).

---

## 20.6 Тести: карти під T‑01…T‑14

Створити файли:

```
tests/integration/test_escalations.py      # T-01, T-02, T-06
tests/integration/test_latency_slippage.py # T-03, T-08
tests/integration/test_action_ratio.py     # T-04
tests/integration/test_chat_commands.py    # T-05
tests/integration/test_sprt_gate.py        # T-09
tests/integration/test_trap_gate.py        # T-10
tests/unit/test_toxicity.py                # T-11
tests/unit/test_atr_warmup.py              # T-12
tests/unit/test_reversal_exit.py           # T-13
tests/integration/test_fail_closed.py      # T-14
```

---

## 20.7 Copilot Prompts (вставляти у файли як коментарі)

**Приклад (calibrator.py):**

```python
"""
COPILOT_PROMPT:
Implement IsotonicCalibrator with fit/predict_p/e_pi_bps.
- Keep p in [0,1], monotonic vs score.
- Fallback to Platt sigmoid if isotonic not available.
- Provide thorough docstrings and type hints.
- Add logging via structlog: event name 'calibrator.entry'.
"""
```

**Приклад (features.py — Binance TFI):**

```python
"""
COPILOT_PROMPT:
Implement trade flow aggregation for Binance trades.
- isBuyerMaker=True => SELL aggressor; False => BUY.
- Support windows 1s/5s/30s, return normalized TFI in [-1,1].
- Add unit tests using tests/fixtures/trades_binance.json.
"""
```

---

## 20.8 Команди для запуску (dev loop)

```
python -m pip install -e .[dev,calibration]
pytest -q
pytest -q tests/integration/test_escalations.py::test_noop_to_cooloff
pytest -q -k "sprt or trap or toxicity"
```

---

## 20.9 Rollout план

1. WP‑G → WP‑A → WP‑D → WP‑H (мінімальний прод‑скелет)
2. Далі WP‑B, WP‑C, WP‑E, WP‑F → тюнінг
3. Shadow 14 днів, спостерігати: Sharpe, slippage, rejection reasons
4. Prod enable з `fail‑closed` тільки після DoD

---

## 20.10 Acceptance (загальний чеклист перед merge)

* [ ] Всі модулі мають докстрінги/тайпінг
* [ ] Події емітяться з валідними кодами
* [ ] Конфіг v4‑min валідний, кастомні поля відхиляються
* [ ] Інтеграційні T‑01…T‑14 зелені
* [ ] Дашборди метрик підключені (або мок‑репорти)
* [ ] Режими ваг документовані в PR

---

## 20.11 Fallback Policy

* Калібратор не готовий → Platt sigmoid
* SPRT деградує по latency → скіпнути SPRT і вимагати сильніший `score ≥ θ_hard`
* Немає TRAP‑метрик → gate вимкнено, але `penalty(OBI×TFI misalign)=hard` (score\*=0)
* Будь‑який парсинг/observability issue → `AURORA.HALT` + `/ops reset`

---

# 21) Hotfix & Fundamental Upgrade — Copilot Task List (R1)

> **Мета R1**: (a) негайно виправити інверсію **TFI** для Binance; (b) перейти від порогу `score` до **очікуваної дохідності** `E[Π]` як головного правила входу; (c) зафіксувати обов’язкові **latency/slippage/TRAP** гейти.
>
> **Формат:** готові картки для GitHub Issues / Copilot. Пріоритезація в порядку виконання. Всі таски ідемпотентні й мають Acceptance.

## 21.1 Пріоритет та порядок виконання

1. **HOTFIX‑G1**: Binance TFI semantics (критично)
2. **UPGRADE‑A2**: Entry Engine на базі `E[Π]` (калібратор + гейт)
3. **GUARD‑D2**: Latency‑guard p95 ≤ 30–35мс (fail‑closed)
4. **GUARD‑D3**: Slippage‑guard через “liquidity ahead” (η·b)
5. **GUARD‑C2**: TRAP v2 — безперервна метрика (z‑score)
6. **SCORE‑F2**: Режимні ваги (tight/normal/loose) — як вхід у калібратор
7. **CHAT‑H2**: Розширення /aurora status та налаштувань (π\_min, η, L\_max)
8. **TEST‑SUITE‑R1**: Нові/оновлені тести T‑15…T‑20

---

### 🔥 HOTFIX‑G1 — Binance TFI Semantics (Critical)

**TASK\_ID:** R1‑HOTFIX‑G1
**Goal:** Усунути інверсію TFI: `isBuyerMaker=True ⇒ SELL агресор`, `False ⇒ BUY`.

**Files:** `core/scalper/features.py`, `tests/unit/test_binance_tfi.py`, `tests/fixtures/trades_binance.json`

**Steps (Copilot):**

1. Оновити агрегацію TFI для вікон 1s/5s/30s (нормалізація до \[−1,1]).
2. Додати golden‑тести (фікстура з міксом трейдів True/False).
3. Логувати `V_mkt_buy, V_mkt_sell, TFI_W` при debug.

**Acceptance:** `tests/unit/test_binance_tfi.py` зелені; інтеграційний smoke не змінює інші фічі.

---

### ⚙️ UPGRADE‑A2 — Expected‑Return Entry Engine (score→p̂→E\[Π])

**TASK\_ID:** R1‑UPGRADE‑A2
**Goal:** Замість порогу `score` використовувати гейт `E[Π] > π_min`.

**Files:** `core/scalper/calibrator.py`, `core/scalper/score.py`, `core/aurora/pretrade.py`, `configs/v4_min.yaml`, `tests/integration/test_expected_return_gate.py`

**API/Config (додати):**

```yaml
risk:
  pi_min_bps: 2.0     # мін. маржа в bps (≈ 0.2×ATR_bps стартово)
slippage:
  eta_fraction_of_b: 0.3
```

**Steps:**

1. Калібратор (ізотоніка → Platt fallback) `score → p̂`.
2. Обчислити `E[Π] = p̂·b − (1−p̂)·a − (fees_bps + slip_bps(q))`.
3. Pre‑trade: дозволити вхід **лише** якщо `E[Π] > pi_min_bps`.
4. Логувати на ENTRY: `score,p̂,a,b,fees,slip,E[Π],regime`.

**Acceptance:** `tests/integration/test_expected_return_gate.py::test_entry_condition_positive` зелений; `::test_fee_slip_push_to_negative` блокує.

---

### 🚦 GUARD‑D2 — Latency Guard (fail‑closed)

**TASK\_ID:** R1‑GUARD‑D2
**Goal:** Заборонити торгівлю, якщо `p95(loop_latency_ms) > L_max`.

**Files:** `core/aurora/pretrade.py`, `core/aurora/policy.py`, `tests/integration/test_latency_guard.py`

**Config:** `aurora.latency_guard_ms: 30` (старт 30–35мс; критичний 50мс для hard‑halt).

**Acceptance:** Т‑03 оновити; додати `test_latency_guard_blocks_when_p95_exceeds`.

---

### 🌊 GUARD‑D3 — Slippage Guard (liquidity ahead)

**TASK\_ID:** R1‑GUARD‑D3
**Goal:** Блок при `slip_bps(q) > η·b`.

**Files:** `core/scalper/score.py` (hook для оцінки), `core/aurora/pretrade.py`, `tests/integration/test_slippage_guard.py`

**Acceptance:** `test_slippage_guard_blocks_on_excess`, `test_slippage_guard_allows_under_eta` зелені.

---

### 🕳️ GUARD‑C2 — TRAP v2 (continuous z‑score)

**TASK\_ID:** R1‑GUARD‑C2
**Goal:** Замість бінарного флага — `TrapScore = z((Cancel−Repl)/(Trades+ε))·sign(OBI)`, lookback 1–3s; гейт при `>p95`.

**Files:** `core/scalper/trap.py`, `tests/integration/test_trap_zscore_gate.py`

**Acceptance:** Блок за `p95`; FPR під контролем у мок‑реплеї.

---

### 🧭 SCORE‑F2 — Regime Weights as Input to Calibrator

**TASK\_ID:** R1‑SCORE‑F2
**Goal:** Обчислювати `score_R = w_R^T x̂` для `R∈{tight,normal,loose}`, але **вхід у калібратор/гейт E\[Π]**, не прямий поріг.

**Files:** `core/scalper/score.py`, `configs/v4_min.yaml`, `tests/unit/test_regime_weights.py`

**Acceptance:** Детермінізм; таблиця `w_R` у PR; інтеграційний smoke з 3 режимами.

---

### 💬 CHAT‑H2 — Chat Surface: E\[Π]/p̂/slip у статусі + сеттери

**TASK\_ID:** R1‑CHAT‑H2
**Goal:** Розширити `/aurora status` полями `p̂, E[Π], slip_bps_est`; додати команди: `/risk set pi_min <bps>`, `/ops set lmax <ms>`, `/ops set eta_slip <0..1>`.

**Files:** `core/chat/commands.py`, `tests/integration/test_chat_commands.py`

**Acceptance:** Команди працюють; статус відображає нові поля; sticky‑critical алерти незмінні.

---

### 🧪 TEST‑SUITE‑R1 — Нові/оновлені тести

**TASK\_ID:** R1‑TEST‑SUITE
**Files:**

```
tests/integration/test_expected_return_gate.py    # T‑15
tests/unit/test_binance_tfi.py                    # T‑16 (оновл.)
tests/integration/test_latency_guard.py           # T‑17
tests/integration/test_slippage_guard.py          # T‑18
tests/integration/test_trap_zscore_gate.py        # T‑19
tests/integration/test_chat_commands.py::R1       # T‑20 (статус/сеттери)
```

**Acceptance:** Усі нові тести зелені; попередні T‑01…T‑14 не ламаються.

---

## 21.2 Швидкі підказки до PR (diff‑скетчі)

* **features.py (TFI):** заміна логіки `isBuyerMaker` і нормалізації; docstring з посиланням на Binance semantics.
* **calibrator.py:** клас `IsotonicCalibrator`; fallback Platt; метод `e_pi_bps(CalibInput)`.
* **pretrade.py:** новий гейт `E[Π] > pi_min_bps`, перевірки latency/slippage/TRAP, емісія подій `AURORA.RISK_WARN`/`AURORA.COOLOFF_START`.
* **commands.py:** розширення `/aurora status`; нові сеттери параметрів.
* **configs/v4\_min.yaml:** додати `risk.pi_min_bps`, `slippage.eta_fraction_of_b`.

---

## 21.3 Міграція конфігу (snippet)

```diff
aurora:
   enabled: true
-  latency_guard_ms: 250
+  latency_guard_ms: 30
slippage:
+  eta_fraction_of_b: 0.3
risk:
+  pi_min_bps: 2.0
```

---

## 21.4 Rollout & Safety

1. Merge **HOTFIX‑G1** окремим PR → tag `r1-hotfix-tfi`.
2. Merge **UPGRADE‑A2** + **GUARD‑D2/D3/C2** за фіче‑гілками → staging replay.
3. Shadow ≥ 14 днів; увімкнути прод тільки при Sharpe>1.5, rejection‑рейти в нормі.
4. Увесь прод у режимі **fail‑closed**; будь‑яка деградація — `HALT` до ручного `/ops reset`.
