# AURORA v1.2 — Unified Certifiable Regime‑Aware Trading

**Prometheus 3.0 × NFSDE‑Cert × CADER‑патчі**
Версія: v1.2 (doctoral‑level concept) • Автор: Мудрець (GPT‑5 Thinking)

---

## 0. Преамбула та дослідницька позиція

Ця робота формує унітарну, сертифіковану та режимно‑адаптивну концепцію алгоритмічного трейдингу й управління екстремальними ризиками, яка об’єднує три лінії: (i) **фізично узгоджена генеративна динаміка** (NFSDE з rough‑пам’яттю та Леві‑стрибками), (ii) **режимна інтерпретація і прийняття рішень у реальному часі** (Prometheus 3.0), (iii) **сертифікаційні гарантії і переносимість** (conformal/DRO, TVF/CTF). Додані патчі CADER: **режимно‑залежні параметри ядра**, **динамічна α у conformal**, **κ⁺** та **TVF 2.0**. Ми зберігаємо архітектуру **teacher–student**: NFSDE‑вчитель (офлайн exactness) → DSSM‑студент (онлайн latency ≤ 100 мс).

---

## 1. Онтологія, нотація і гіпотези

### 1.1 Нотація

* $X_t\in\mathbb{R}^d$ — вектор процесів (ціни, вола, обсяг, сурогати).
* $x_t\in\mathbb{R}^p$ — фічі (OHLCV, ATR, RSI‑lite, VWAP, realized vola).
* $r_t=\log P_t-\log P_{t-1}$ — лог‑прибутки.
* $z_t^S\in\mathbb{R}^{d_S}$ — латент DSSM‑студента; $\tilde z_t^T\in\mathbb{R}^{d_T}$ — ембед вчителя (NFSDE).
* $H\in(0,1)$ — індекс Херста; $\xi$ — tail index; $\theta_e$ — extremal index; $\lambda_U$ — upper tail dependence.
* $\kappa\in[0,1]$ — мета‑невизначеність; $\kappa_+$ — бленд із BCC; **ACI** — ARMA Crossbar Index.
* **Router** — класифікатор режимів $\in\{\mathrm{AR},\mathrm{ARMA},\mathrm{GARCH}\}$.
* **TVF 2.0**: CTR, DCTS, $|\Delta\hat\xi|,|\Delta\hat H|$ — порогові умови переносу.

### 1.2 Гіпотези (H)

* **H1 (Фізична адекватність):** NFSDE із rough+Леві відтворює хвости й пам’ять реальних фінансових рядів; $I=\{H,\xi,\theta_e,\lambda_U\}$ узгоджуються на SEB+ та історії.
* **H2 (Дистиляція):** DSSM, дистильований від NFSDE через Signature‑MMD, tail‑matching та KL/OT у латенті, відтворює **операційно релевантні** властивості при latency ≤ 50 мс.
* **H3 (Режимність):** Режимно‑залежні параметри ядра ($f,g,h,\lambda,H$) підвищують стабільність керування tail‑ризиком у TRANS‑зонах (ACI↑), якщо $H$ — кусочно‑сталий або повільно мінливий.
* **H4 (Сертифікація):** ICP з масштабуванням $\hat\sigma_t$, динамічна $\alpha(z,\mathrm{ACI})$ і DRO‑ES гарантують ES‑контроль без погіршення Sharpe.
* **H5 (Переносимість):** TVF 2.0 (CTR≥0.8, DCTS≥0.7, $|\Delta\hat\xi|<0.1, |\Delta\hat H|<0.05$) коректно відсікає непридатні домени.

---

## 2. Ядро: Режимно‑залежне NFSDE (mBm‑constrained)

### 2.1 Модель

$$
\mathrm{d}X_t = f_\Theta(X_t,t,z_t)\,\mathrm{d}t + g_\Theta(X_t,t,z_t)\,\mathrm{d}W_t^{H(z_t)} + \int_{\mathbb{R}^m} h_\Theta(X_{t^-},z_t,u)\,\tilde N(\mathrm{d}t,\mathrm{d}u),
$$

де $z_t$ — режимний ембед від Router/DSSM; $H(z_t)$ — **кусочно‑сталий** на блоках довжини $B$, $|H_{b+1}-H_b|\le\varepsilon_H$. Інтенсивність стрибків $\lambda(x,t,z_t)$ — режимно‑залежна; опція — **Hawkes** із гілкуванням $\eta(z_t)$ (спектральний радіус < 1).

### 2.2 Умови існування/єдиності (скетч)

Локально Ліпшицеві $f,g,h$ з лінійним ростом; інтегровність Леві‑міри; fBM‑інтеграл у сенсі Young/rough‑paths; для mBm — локальна регулярність $H(t)$. У практиці — дискретизація Euler–Maruyama+Ogata, контроль збіжності при $\Delta\to0$.

### 2.3 Функціонал навчання вчителя

$$
\mathcal{J}_T = -\log p_\Theta(X_{0:T}) + \lambda_{\mathrm{sig}}\,\mathrm{MMD}(S(X),S(\hat X)) + \lambda_{\mathrm{sep}}\,(\|\Lambda_{\mathrm{jump}}\|_1 + \|\nabla_x g\|_{H^1}^2).
$$

---

## 3. Студент: DSSM та дистиляція

### 3.1 DSSM (ELBO + стабільність)

$$
\begin{aligned}
z_t^S &\sim p_\phi(z_t^S|z_{t-1}^S),\quad x_t\sim p_\theta(x_t|z_t^S),\quad q_\psi(z_t^S|z_{t-1}^S,x_t),\\
\mathcal{L}_{\mathrm{ELBO}} &= \sum_t \mathbb{E}_{q_\psi}[\log p_\theta(x_t|z_t^S)] - \mathrm{KL}(q_\psi\|p_\phi) - \lambda_J\,\|J_t\|_F^2.
\end{aligned}
$$

Емісія — Student‑t/GMM; online‑квантілі для швидкого прогнозу.

### 3.2 Дистиляція від вчителя

$$
\mathcal{L}=\mathcal{L}_{\mathrm{ELBO}}+\lambda_{\mathrm{sig}}\,\mathrm{MMD}+\lambda_{\mathrm{tail}}\sum_{u\in I} w_u\,\rho(\hat u^S,\hat u^T)+\lambda_{\mathrm{KD}}\,\mathrm{KL}(\mathcal{N}(z^S;\mu_S,\Sigma_S)\|\mathcal{N}(\tilde z^T;\mu_T,\Sigma_T)) + \lambda_{\mathrm{sep}}\,\mathcal{L}_{\mathrm{sep}}.
$$

---

## 4. Сертифікація: ICP (динамічна α), CCC та DRO‑ES

### 4.1 ICP з масштабуванням і динамічною α

Скор: $s_i=\frac{|y_i-\hat y_i|}{\hat\sigma_i}$. Квантиль: $q_\alpha=\mathrm{Quantile}_{1-\alpha}\{s_i\}$. Інтервал: $[\hat y\pm q_\alpha\hat\sigma]$.
$\alpha$ динамічна: $\alpha(z,\mathrm{ACI})=\mathrm{clip}(\alpha_0+\alpha_1\mathbf{1}_{\text{TRANS}}+\alpha_2\,\mathrm{ACI}_{EMA}, \alpha_{\min},\alpha_{\max})$.

### 4.2 κ та κ⁺

$$
\kappa=w_s U_{\text{state}}(z)+w_m U_{\text{model}}(\text{router})+w_f U_{\text{forecast}}(\text{PI width}),\quad
\kappa_+=\gamma\,\kappa+(1-\gamma)\,\mathrm{BCC}(\tau;W).
$$

$\gamma$ обираємо грідом: мінімізація $\mathrm{CVaR}_{0.95}$ при $\mathrm{Sharpe}\ge S_{\min}$.

### 4.3 CCC та DRO‑ES

* **CCC**: активуємо інтервали/політики лише якщо каузальна валідація хвостів (Granger‑Extremum) пройдена.
* **DRO‑ES** (Wasserstein‑куля): $\min_{w,t,\xi_i} t+\frac{1}{\alpha n}\sum\xi_i\ \ \text{s.t.}\ \xi_i\ge L(w;X_i)-t,\ \xi_i\ge0$.

---

## 5. Режими, Router, ACI і фільтри

### 5.1 NN\_router та SLERP‑BIC

Дані від вчителя+реальні → SLERP по латентах → BIC(AR/ARMA/GARCH) → навчання Router; калібрування ECE≤0.05; монотонність по SLERP ≤10% порушень.

### 5.2 ACI (визначення і стабілізація)

$\mathrm{ACI}(z)=\|\hat\phi_{AR}(z)-\hat\phi_{ARMA}(z)\|_2/(\sigma_\phi+\varepsilon)$.
Фільтри: vola>$v_{\min}$, volume>квантиль, momentum>порогу; гістерезис $a_{on}>a_{off},\ m_{on}>m_{off}$, мін. тривалість TRANS.

---

## 6. Переносимість: TVF 2.0

**READY:** CTR≥0.8, DCTS≥0.7, $|\Delta\hat\xi|<0.1, |\Delta\hat H|<0.05$.
NOT READY → ICM + conservative rf (DRO‑ES), паралельна recalibration.

---

## 7. Метрики та тести

* Хвости: Хілл $\hat\xi$, $\hat\theta_e$, $\hat\lambda_U$, Tail‑Wasserstein.
* Сертифікація: BCC($\tau$), покриття≈номіналу; ECE Router ≤0.05.
* Ризик: VaR/ES backtests (Christoffersen, Acerbi–Szekely), ARG<0.10.
* Прогноз: Diebold–Mariano для loss‑рядів.
* Переносимість: CTR, DCTS, інваріанти.
* Latency: ≤100 мс (SLO).

📑 Доповнення до концепції Аврори
7. Самонавчальний профіль успішних угод

Аврора не тільки фільтрує угоди в реальному часі, але й збирає статистику результатів протягом торгівлі, щоб формувати “еталонний профіль” успішних трейдів. Це дозволяє системі адаптуватися під ринок і зменшувати кількість неефективних входів.

🔎 7.1. Логування угод

Для кожної угоди (в т.ч. shadow/testnet/prod) зберігається запис у trades_log.csv/json.

Поля:

timestamp, symbol, side, pnl%, tp/sl result

latency, slip_bps, spread_bps

trap_score, cancel_rate, repl_rate

expected_return (score, a_bps, b_bps)

risk_ctx (size_scale, base_notional, scaled_notional)

📊 7.2. Статистичний аналіз

Угоди діляться на успішні (TP > SL, pnl > 0) і невдалі.

Для обох груп рахується розподіл ключових метрик (latency, slip, trap_score, score).

На основі цього формується кластер ознак успішних угод.

🧠 7.3. Профілювання та використання

Новий модуль Profiling Gate:

При кожному pretrade/check метрики угоди порівнюються з “профілем успіху”.

Якщо угода схожа на успішні → пропускається.

Якщо угода сильно відхиляється → блокується або позначається як “ризикова”.

Рівень схожості можна рахувати через:

прості статистичні межі (mean ± std),

або ML (PCA/autoencoder, KMeans clustering у latent space).

⚖️ 7.4. Режим роботи

Learning mode: Аврора накопичує історію угод (1–4 тижні).

Profiling mode: Використовує зібраний профіль як додатковий gate.

Human-in-the-loop: Аврора не переписує правила сама, а формує рекомендації → трейдер підтверджує/вносить у конфіг.

🎯 7.5. Очікуваний ефект

Система поступово “вчиться” відсіювати угоди з низькою ймовірністю успіху.

Зниження кількості зайвих входів → кращий Sharpe Ratio, менший drawdown.

Підвищення дисципліни: бот торгує тільки тоді, коли умови подібні до історично прибуткових.

## 8. Алгоритмічні схеми (ескізи)

### 8.1 Спільне тренування (вчитель→студент)

```
fit_nfsde(Θ); generate_SEB_plus_targets()
for seq in union(data_real, data_teacher):
  zT = teacher_embed(seq)
  zS = dssm_encode(seq)
  loss = ELBO + λsig*MMD + λtail*tail_penalty(I_S,I_T) + λKD*KL(zS||zT) + λsep*sep
  step(loss)
```

### 8.2 Динамічна α в ICP

```
alpha = clip(alpha0 + a1*is_transition + a2*ACI_ema, amin, amax)
q = quantile(scores_cal, 1-alpha)
L,U = yhat - q*σhat, yhat + q*σhat
```

### 8.3 Калькуляція κ⁺ і політика

```
kappa_plus = γ*kappa(z, logits, (q025,q975), post.mu, post.Sigma) + (1-γ)*bcc.update(L,U,y)
policy = PASS if kappa_plus>τp else DERISK if kappa_plus>τd else STANDARD
```

### 8.4 DRO‑ES

```
scen = tail_scenarios(z, xi_hat, theta_e_hat, lambdaU_hat, n=512)
w* = dro_es_optimize(L, scen, alpha=0.95, eps=eps_of_regime(z))
```

---

## 9. Інженерія, сервіс і SRE

* FastAPI `/inference`, `/metrics`, `/health`; latency‑бюджет ≤100 мс.
* Prometheus/Grafana: κ, κ⁺, coverage, ECE, PSI/KL/MMD, regime‑mix, latency, error‑rate.
* Kill‑switch: κ⁺‑спайки, coverage<номінал−δ, data‑lag, error‑rate>порога.
* Canary 10% → 100% з rollback.

---

## 10. План валідації і приймальні критерії

* **Backtest:** Sharpe ≥ базовий +0.3; Sortino ≥ +0.3; CVaR(95%) ≤ 10%; latency ≤ 100 мс.
* **Shadow‑live 14 днів:** та самі KPI + стабільність; спрацювання тригерів дрейфу.

---

## 11. Наукові питання (для подальшого дослідження)

1. Ідентифікація джерел хвостів (rough vs jumps) в умовах mBm: достатні умови відокремлюваності.
2. Теорія динамічної conformal‑калібровки з ендогенною $\alpha(z,\mathrm{ACI})$: межі покриття при нестаціонарності.
3. Гарантії переносимості TVF 2.0: статистична потужність і помилка 1/2 роду при кусочно‑сталій зміні інваріантів.
4. Каузальна стабільність CTF під стрибками: робастні тести Granger‑Extremum із FDR‑контролем.
5. DRO‑ES у Wasserstein‑кулі для залежних даних: швидкість збіжності і чутливість до вибору $\varepsilon$.

---

## 12. Дорожня карта R\&D → Прод

* **Фаза A (1–2 тижні):** NFSDE‑вчитель, SEB+, дистиляція DSSM; Router; ICP‑калібрування; κ‑пороги (CVaR‑грід).
* **Фаза B (3 тиждень):** Backtests + статистика (DM, Christoffersen, ES); абляції −κ/−ACI/−Router.
* **Фаза C (4 тиждень):** Shadow‑live 14 днів; fine‑tune порогів; SRE‑алерти.
* **Фаза D (5+):** Canary→100%; процедурний регламент ретрейнів і випусків.

---

## 13. Основна задача і ціль

**Задача:** розробити AURORA v1.2 — сертифікований режимно‑адаптивний торговий шар із гарантованим контролем хвостових ризиків та переносимістю.
**Ціль:** досягти ES$_{95}$ −25% проти бази, Sharpe +0.3, CTR≥0.8, latency ≤100 мс, із дотриманням coverage/ECE та SRE‑SLO.
**Результати:** підвищена стійкість до брейків, стабільні інтервали та керований ризик, готовність до масштабування по активах/TF.

---

## 14. Поглиблення NFSDE: ідентифікація, дискретизація, стабільність

### 14.1 Параметризація f, g, h, lambda і архітектура

* Drift: f\_Theta(x,t,z) = A(z) x + b(z) + u\_Theta(x,t,z), де A(z) має власні значення з від'ємною реальною частиною (стабілізація спектра).
* Diffusion: g\_Theta(x,t,z) = C(x,t,z) C(x,t,z)^T з обмеженням норми C (спектральний кліпінг).
* Jumps: h\_Theta(x,z,u) = J(x,z) u. Інтенсивність lambda(x,t,z) = lambda0(z) + alpha(z)^T phi(x,t). Опція Hawkes: lambda\_t = mu(z) + (phi\_z \* dN)\_t з нормою ядра < 1.
* H(z): кусочно-сталий на блоках B з |Delta H| <= eps\_H.

### 14.2 Оцінювання H і вибір блоків

* Оцінки H через wavelet/Whittle на ковзному вікні; правило плато спектральної щільності.
* Вибір B з компромісу Var(H\_hat) vs bias симулятора; стартово B в \[128, 512] для 1–5m TF.

### 14.3 Розділення rough vs jumps

* Біпауер-варіація: BV = sum |Delta X\_i| |Delta X\_{i-1}|; якщо RV-BV значуще > 0, то є стрибки.
* p-варіації: масштабування sum |Delta X|^p по сітках; rough змінює нахил, стрибки дають аномалії.
* Регуляризація у навчанні: lambda\_sep (L1 на інтенсивності стрибків + гладкість дифузії) + A/B абляції (no-jumps, no-rough).

### 14.4 Дискретизація і похибка

* Схема: Euler–Maruyama + компенсація стрибків; інкременти fBM у межах блоку B (Davies–Harte).
* Порядок похибки \~ Delta^{min(1, H + 0.5)} у MSE; перевірка збіжності при Delta у {1, 1/2, 1/4}.

### 14.5 Градієнти і стабільність

* Pathwise + adjoint; кліпінг градієнта; step-anneal кроку інтегратора; контроль спектра A(z) та норми C.

### 14.6 Псевдокод симулятора

```
for block in H_blocks:  # H constant in block
    dW_H = davies_harte(len_block, H=block.H)
    for k in range(len_block):
        x = x + f(x,t,z)*dt + g(x,t,z) @ dW_H[k] + jump_increment(x,t,z)
        t = t + dt
```

---

## 15. DRO-ES: від первинної до двоїстої форми, реалізація

### 15.1 Постановка (Wasserstein W1)

Мінімізувати найгірший ES на кулі Вассерштейна радіуса eps навколо емпіричного розподілу:
min\_w sup\_{Q: W1(Q, P\_n) <= eps} ES\_alpha(L(w; X)), де L(w; X) = - w^T X.

### 15.2 Скаляризація (Rockafellar–Uryasev) і двоїстість

Еквівалент: min\_{w, t} t + (1/(alpha n)) sum max(0, L(w; X\_i) - t), w в допустимому множині. Для ліпшицевої L отримаємо штраф eps \* ||w||\_\* у цілі.

### 15.3 Реалізація (cvxpy)

```
w = cp.Variable(d)
t = cp.Variable()
xi = cp.Variable(n, nonneg=True)
loss = -X @ w
constraints = [xi >= loss - t, cp.norm(w,2) <= R]
obj = cp.Minimize(t + (1/alpha/n)*cp.sum(xi) + eps*cp.norm(w,2))
prob = cp.Problem(obj, constraints)
prob.solve(solver=cp.ECOS)
```

* Вибір eps: функція режиму/ACI (більший у TRANS), калібрувати по ES-валідації.
* Сценарії: історичні + tail-synthetic (SEB+ або вчитель), 512–2048 точок.

---

## 16. Conformal з динамічною alpha

### 16.1 Вагові/блочні схеми

Weighted ICP (ваги \~ exp(-lambda \* вік)); Block ICP для не-обмінності.

### 16.2 Покриття і BCC

Повільна зміна alpha\_t дає покриття близько 1 - alpha\_t з похибкою O(1/W), де W — розмір вікна BCC. Онлайн-квантілі через t-digest/Greenwald–Khanna.

---

## 17. Тести ідентифікації та каузальності

* Jump vs rough: тест Barndorff–Nielsen–Shephard (RV vs BV), p-variation slope.
* CTF: Granger-Extremum на індикаторах перевищень, FDR-контроль; вмикати CCC при F1 >= 0.75.

---

## 18. Гіперпараметри і ресурси

* Ресурси: вчитель 1x A100 80GB або 2x 3090; студент 1x T4/V100.
* Навчання: mixed precision, grad accumulation, micro-batch, pinned memory.
* Сітки: lambda\_sig \[0.1,2], lambda\_tail \[0.1,1], lambda\_KD \[0.01,0.5], lambda\_sep \[1e-4,1e-2].

---

## 19. Калібрування і чутливість

* (tau\_d, tau\_p): грід \[0.2, 0.95] — мінімізуємо ES95 при Sharpe >= S\_min; vola-скейлінг порогів.
* gamma для kappa+ — грідом; вибір по Pareto (ES vs Sharpe).
* B, eps\_H — сенситивіті на ES/coverage/latency; обираємо мін-ризик при дотриманні SLO.

---

## 20. Аудит і комплаєнс

Explainability: логи Router (prob, ECE), ACI-стани, drivers policy, компоненти kappa. Audit trail: версії ваг і конфігів, seeds, підписані артефакти, відтворювані бек-тести. RBAC/Secrets: vault, токени поза кодом.

---

## PHASE 0 STATUS (Implementation Progress)

Готово:
1. Data Pipeline (інжестер + конектори-заглушки + feature engineering: ATR, RSI-lite, VWAP, realized vola, momentum, MACD, Bollinger width).
2. Gap filling & time grid enforcement (`ensure_time_grid`).
3. Unit tests (feature set, gap filling) інтегровані в CI.
4. CI/CD workflow (GitHub Actions): lint (ruff), tests+coverage (>=70%), Docker build.
5. Dockerfile (production slim) для FastAPI сервісу.
6. Monitoring: Prometheus метрики (latency histogram, kappa_plus, regime, requests counter) + базовий Grafana dashboard JSON.

Pending / Next (перехід до Phase 1):
1. Реалізація/дистиляція NFSDE teacher (симулятор + SEB+ генерація).
2. DSSM тренування з дистиляцією (підключити datasets Parquet pipeline).
3. Router calibration (ECE ≤ 0.05) на реальних+симульованих даних.
4. Розширення метрик: coverage, ECE, κ decomposition (state/model/forecast), tail інваріанти.
5. Підготовка сценаріїв для підсинтетичних хвостів (SEB+) для майбутнього DRO‑ES.

Гейт переходу до Phase 1: підтверджено — інфраструктурні артефакти Phase 0 виконані (✅). Починаємо реалізацію Core Models.

---

## PHASE 2 SNAPSHOT (Adaptive ICP + Acceptance Layer — Current Implementation)

Status: Partial implementation of Certification Layer ahead of original schedule to de‑risk uncertainty governance. Components live in `living_latent/` namespace (decoupled from legacy `certification/` scaffolding for clarity and progressive migration).

Implemented (✅):
1. AdaptiveICP (`living_latent/core/icp_dynamic.py`):
    - Online P² quantile estimator with cold‑start fallback (empirical until n≥100).
    - Dynamic alpha adaptation via signed coverage error (EMA) with base/transition learning rates (eta_base=0.01, eta_transition=0.03) and cooldown to avoid over‑reaction.
    - Transition inflation heuristic (capped interval width multiplier ≤1.25) based on recent misses + regime shift flag.
    - Stats/telemetry hooks (expose current alpha, coverage_ema, q_hat, inflation_factor).
2. Surprisal v2 (`living_latent/core/surprisal.py`): robust tail surprisal = Huber(|e|/σ) blended with log1p; winsorized p95 utility for guard rails.
3. Acceptance Orchestrator (`living_latent/core/acceptance.py`):
    - Maintains rolling metrics: coverage streaks, latency p95 proxy, kappa / kappa+ (meta‑uncertainty + BCC blend).
    - Decision states: PASS / DERISK / BLOCK with guard hierarchy (hard guards override soft kappa thresholds).
    - Penalties: coverage deficit persistence, latency overruns, surprisal spikes (exceeding winsorized p95 * inflation).
4. DRO‑ES lightweight objective (`living_latent/core/dro_es.py`): monotonic test harness for eps‑grid sanity separate from full cvxpy optimizer (`certification/dro_es.py`).
5. Replay Script (`living_latent/scripts/run_r0.py`): offline log ingest → JSON summary (coverage, p95 latency, surprisal p95, decision distribution) to support forthcoming calibration batch (Phase 2b).
6. Trading Hook Integration (`trading/main_loop.py`): acceptance decision + info returned alongside forecast (currently advisory; does not yet gate execution size).
7. Governance Config (`living_latent/cfg/master.yaml`): central thresholds (icp target coverage, kappa τ_d / τ_p, guard ceilings, eps_grid for DRO‑ES) enabling profile swaps (default vs shadow).
8. Test Suite Additions (`tests/`):
    - `test_icp_stream.py`: AR(1)+outlier+regime‑shift scenario validates adaptive coverage within ±0.03 of target after burn‑in.
    - `test_acceptance_decision.py`: kappa monotonicity, guard triggers (surprisal, latency), coverage streak escalation → BLOCK.
    - `test_dro_es_behavior.py`: monotonicity of surrogate DRO‑ES objective across eps grid.

Key Fixes / Lessons:
* Corrected alpha adaptation sign (early bug produced over‑coverage ~0.99). Now controller increases alpha only when empirical coverage > target (intervals shrink) and decreases alpha when under‑covered.
* Deferred P² utilization until sufficient sample size to reduce initial quantile noise.
* Added inflation cap + cooldown preventing oscillatory widening under clustered misses.

Pending / Next (Phase 2b Calibration & Gating):
1. Migrate trading loop from legacy `DynamicICP` placeholder to `AdaptiveICP` instance (single source of truth) or wrap for backward compatibility.
2. Activate execution gating: map PASS / DERISK / BLOCK to position scaling factors (e.g., 1.0 / 0.5 / 0.0) with hysteresis to avoid flip‑flopping.
3. Calibrate kappa τ_d, τ_p and surprisal guard multipliers on shadow log distribution (bootstrap ES / Sharpe constraints).
4. Integrate real latency/coverage streaming metrics into Prometheus (export alpha, coverage_error, kappa, decision share).
5. Expand DRO‑ES integration: swap test surrogate with full optimizer in acceptance feedback loop (tie eps regime logic to observed volatility + regime transitions).
6. Documentation: add acceptance state machine diagram & metrics glossary (scheduled).

Risks / Watchpoints:
* Over‑tightening alpha under non‑stationary shocks (mitigated via learning rate split + cooldown; monitor transient coverage drawdowns in replay).
* Decision churn near thresholds (pending hysteresis and minimum dwell time design).
* Divergence between advisory acceptance in trading and enforced gating (short window of dual behavior — minimize by prioritizing migration Task 1).

Success Gate for concluding Phase 2b:
* 30k+ shadow predictions replayed → stable coverage within target band, <5% BLOCK rate absent synthetic fault injection, DERISK dominated by genuine volatility clusters.
* Calibrated thresholds produce ≤2% ES overshoots vs baseline while retaining ≥90% nominal coverage.

Note: This snapshot intentionally precedes full teacher/student deployment; acceptance layer is being validated early with synthetic & proxy data to reduce downstream integration risk.

---

## UPDATED PROGRESS (2025-08-18)

Виконано після останнього snapshot (інкрементальні досягнення):
1. Execution Risk Gate (позиційне масштабування PASS/DERISK/BLOCK + Prometheus метрики причин) інтегровано у `trading/main_loop.py`.
2. Нормалізація калібрувальних метрик + обмежений objective ([-1,1]) через `living_latent/core/metrics_io.py`; застосовано в `scripts/run_r0.py`.
3. Пост-аналіз `scripts/summarize_run.py` (surprisal p95 pre/post, latency p95, trigger flags) — допис метаданих у acceptance JSON.
4. Snapshot persistence: серіалізація/відновлення стану AdaptiveICP + Acceptance FSM (atomic JSON) для warm restart стабільності.
5. Розширені тести: objective bounds, execution gating summary, trigger summarization (усі green).
6. Додаткові метрики Prometheus: лічильники блокувань/DERISK, шкала ризикового скейлінгу, події snapshot save/load.
7. Верифікація покриття AdaptiveICP на синтетичному AR(1)+shift — стабілізація у таргетному діапазоні (±0.03) ✔.
8. Kappa/Kappa+ бленд із BCC стабільно в робочому коридорі [0.2,0.8].

Залишилось до мінімально осмисленого Shadow:
- NFSDE teacher + дистиляційні таргети (реальні чекпойнти відсутні).
- Deterministic feature extraction (прибрати псевдовипадкові/заглушки).
- Router temperature calibration (ECE ≤0.05).
- TVF 2.0 + tail інваріанти (Hill, θ_e, λ_U) у live цикл.
- Повний DRO‑ES (cvxpy) замість сурогатного objective.

---

# PRODUCTION IMPLEMENTATION PLAN
**AURORA v1.2 — Детальний план впровадження**
Версія: Implementation v1.0 • Дата: 

---

## I. OVERVIEW

AURORA v1.2 — це трирівнева система алгоритмічного трейдингу з фізично-узгодженою генеративною моделлю (NFSDE), режимно-адаптивним студентом (DSSM) та сертифікованим контролем ризиків. Основна архітектура: офлайн-вчитель генерує точні прогнози, онлайн-студент забезпечує низьку латентність (≤100мс), система сертифікації гарантує контроль хвостових ризиків.

**Ключові компоненти:**
- NFSDE Teacher: rough Brownian + Lévy jumps симулятор
- DSSM Student: дистильована модель для реального часу
- Router: класифікатор ринкових режимів (AR/ARMA/GARCH)
- Certification: ICP + DRO-ES + TVF 2.0
- Monitoring: κ/κ+ метрики невизначеності

---

## II. ROADMAP

### **PHASE 0: Infrastructure & Setup (5 днів)**
**Цілі:** Підготувати інфраструктуру, налаштувати середовище розробки
**Deliverables:** 
- Розгорнуті GPU-кластери (1x A100 для teacher, 1x V100 для student)
- CI/CD pipeline з автотестами
- Data pipeline для історичних даних
- Monitoring stack (Prometheus/Grafana)

### **PHASE 1: Core Models (10 днів)**
**Цілі:** Реалізувати та навчити базові моделі NFSDE та DSSM
**Deliverables:**
- Працюючий NFSDE симулятор з валідацією
- Навчений DSSM з дистиляцією
- Router з ECE ≤ 0.05
- Базові метрики якості

### **PHASE 2: Certification Layer (7 днів)**
**Цілі:** Впровадити систему сертифікації та контролю ризиків
**Deliverables:**
- ICP з динамічною α
- DRO-ES оптимізатор
- κ/κ+ калькулятори
- TVF 2.0 валідатор

### **PHASE 3: Integration & Testing (7 днів)**
**Цілі:** Інтегрувати компоненти, провести backtest
**Deliverables:**
- Повністю інтегрована система
- Backtest результати (Sharpe ≥ base+0.3)
- API endpoints з SLA
- Kill-switch механізми

### **PHASE 4: Shadow Trading (14 днів)**
**Цілі:** Валідація в реальних умовах без ризику
**Deliverables:**
- 14-денний shadow режим
- Звіт про стабільність метрик
- Fine-tuned параметри
- Go/No-Go рішення

### **PHASE 5: Production Launch (7 днів)**
**Цілі:** Поступовий запуск у продакшн
**Deliverables:**
- Canary deployment 10%
- Повний rollout 100%
- SRE playbooks
- Post-launch моніторинг

---

## III. DETAILED STEPS

### **PHASE 0: Infrastructure & Setup**

#### 0.1 GPU Cluster Setup
```bash
# Terraform конфігурація для AWS/GCP
terraform/
├── gpu_instances.tf    # p3.8xlarge (V100) + p4d.24xlarge (A100)
├── networking.tf        # VPC, security groups, load balancers
├── storage.tf          # S3/GCS для моделей, EBS для даних
└── monitoring.tf       # CloudWatch/Stackdriver

# Вимоги:
- CUDA 11.8+, cuDNN 8.6+
- Docker 20.10+ з nvidia-runtime
- Python 3.10, PyTorch 2.0+
```

#### 0.2 Data Pipeline
```python
# data_pipeline/ingester.py
class DataIngester:
    def __init__(self):
        self.sources = {
            'binance': BinanceConnector(),
            'polygon': PolygonConnector(),
            'historical': S3DataLoader()
        }
    
    def fetch_ohlcv(self, symbol, timeframe, start, end):
        # Реалізація з retry logic, validation, gap filling
        pass
    
    def calculate_features(self, df):
        # ATR, RSI, VWAP, realized_vol
        # Returns: pd.DataFrame with 20+ features
        pass
```

#### 0.3 CI/CD Pipeline
```yaml
# .gitlab-ci.yml
stages:
  - test
  - build
  - deploy

unit_tests:
  stage: test
  script:
    - pytest tests/unit --cov=aurora --cov-report=xml
    - coverage report --fail-under=80

integration_tests:
  stage: test
  script:
    - docker-compose up -d test_env
    - pytest tests/integration --timeout=300

model_validation:
  stage: test
  script:
    - python scripts/validate_model.py --checkpoint latest
    - python scripts/check_latency.py --target 100ms
```

### **PHASE 1: Core Models**

#### 1.1 NFSDE Implementation
```python
# models/nfsde.py
class NFSDE(nn.Module):
    def __init__(self, d_state, d_latent, H_blocks=128):
        super().__init__()
        # Архітектура мереж
        self.drift_net = nn.Sequential(
            nn.Linear(d_state + d_latent, 256),
            nn.SiLU(),
            ResBlock(256),
            ResBlock(256),
            nn.Linear(256, d_state)
        )
        
        self.diffusion_net = nn.Sequential(
            nn.Linear(d_state + d_latent, 128),
            nn.SiLU(),
            nn.Linear(128, d_state * d_state)
        )
        
        self.jump_net = JumpNetwork(d_state, d_latent)
        self.H_estimator = HurstEstimator(window=256)
        
    def simulate(self, x0, z_trajectory, dt=1e-3, steps=1000):
        # Euler-Maruyama з rough Brownian та Lévy
        x = x0
        trajectory = [x0]
        
        for block in range(0, steps, self.H_blocks):
            H = self.H_estimator(x, z_trajectory[block])
            dW_H = self._generate_fbm_increments(H, self.H_blocks, dt)
            
            for k in range(self.H_blocks):
                idx = block + k
                if idx >= steps:
                    break
                    
                # Drift
                f = self.drift_net(torch.cat([x, z_trajectory[idx]]))
                
                # Diffusion
                g = self.diffusion_net(torch.cat([x, z_trajectory[idx]]))
                g = g.view(d_state, d_state)
                
                # Jump
                jump = self.jump_net.sample(x, z_trajectory[idx], dt)
                
                # Update
                x = x + f * dt + g @ dW_H[k] + jump
                trajectory.append(x)
                
        return torch.stack(trajectory)
```

#### 1.2 DSSM Student
```python
# models/dssm.py
class DSSM(nn.Module):
    def __init__(self, d_obs, d_latent, d_hidden=512):
        super().__init__()
        # Encoder
        self.encoder = nn.LSTM(
            d_obs, d_hidden, 
            num_layers=3, 
            dropout=0.1,
            batch_first=True
        )
        
        self.mu_net = nn.Linear(d_hidden, d_latent)
        self.logvar_net = nn.Linear(d_hidden, d_latent)
        
        # Prior
        self.prior_net = nn.GRUCell(d_latent, d_latent)
        
        # Decoder
        self.decoder = nn.Sequential(
            nn.Linear(d_latent, d_hidden),
            nn.SiLU(),
            ResBlock(d_hidden),
            nn.Linear(d_hidden, d_obs * 3)  # mean, scale, df for Student-t
        )
        
    def forward(self, x, teacher_z=None):
        # ELBO computation з опціональною дистиляцією
        h, _ = self.encoder(x)
        mu_q = self.mu_net(h)
        logvar_q = self.logvar_net(h)
        
        # Reparameterization
        z = mu_q + torch.exp(0.5 * logvar_q) * torch.randn_like(mu_q)
        
        # Prior
        z_prior = self.prior_net(z[:-1], z[1:])
        
        # Decode
        params = self.decoder(z)
        mu_x, scale_x, df_x = params.chunk(3, dim=-1)
        
        # Losses
        recon_loss = -StudentT(df_x, mu_x, scale_x).log_prob(x).sum()
        kl_loss = kl_divergence(
            Normal(mu_q, torch.exp(0.5 * logvar_q)),
            Normal(z_prior, torch.ones_like(z_prior))
        ).sum()
        
        loss = recon_loss + kl_loss
        
        # Distillation якщо є teacher
        if teacher_z is not None:
            distill_loss = F.mse_loss(z, teacher_z)
            loss += 0.1 * distill_loss
            
        return loss, z
```

#### 1.3 Router Implementation
```python
# models/router.py
class RegimeRouter(nn.Module):
    def __init__(self, d_input, num_regimes=3):
        super().__init__()
        self.backbone = nn.Sequential(
            nn.Linear(d_input, 256),
            nn.LayerNorm(256),
            nn.SiLU(),
            ResBlock(256),
            ResBlock(256),
            nn.Dropout(0.2)
        )
        
        self.classifier = nn.Linear(256, num_regimes)
        self.temperature = nn.Parameter(torch.ones(1))
        
    def forward(self, x):
        features = self.backbone(x)
        logits = self.classifier(features) / self.temperature
        probs = F.softmax(logits, dim=-1)
        return probs, logits
    
    def calibrate_temperature(self, val_loader):
        # Temperature scaling для ECE ≤ 0.05
        self.eval()
        logits_list = []
        labels_list = []
        
        with torch.no_grad():
            for x, y in val_loader:
                _, logits = self(x)
                logits_list.append(logits)
                labels_list.append(y)
        
        logits = torch.cat(logits_list)
        labels = torch.cat(labels_list)
        
        # Optimize temperature
        optimizer = optim.LBFGS([self.temperature], lr=0.01)
        
        def eval_ece():
            scaled_logits = logits / self.temperature
            probs = F.softmax(scaled_logits, dim=-1)
            ece = expected_calibration_error(probs, labels)
            return ece
        
        optimizer.step(eval_ece)
```

### **PHASE 2: Certification Layer**

#### 2.1 ICP with Dynamic Alpha
```python
# certification/icp.py
class DynamicICP:
    def __init__(self, alpha_base=0.1, window=1000):
        self.alpha_base = alpha_base
        self.window = window
        self.calibration_scores = deque(maxlen=window)
        self.aci_ema = 0
        
    def compute_alpha(self, z, aci, is_transition):
        # Динамічна alpha
        alpha = self.alpha_base
        
        if is_transition:
            alpha += 0.02  # Розширення в перехідних зонах
            
        alpha += 0.01 * min(aci, 1.0)  # ACI вплив
        
        return np.clip(alpha, 0.05, 0.20)
    
    def predict_interval(self, y_hat, sigma_hat, z, aci):
        # Обчислення інтервалу
        is_trans = self._detect_transition(z)
        alpha = self.compute_alpha(z, aci, is_trans)
        
        # Квантиль з калібрувального набору
        if len(self.calibration_scores) > 100:
            q = np.quantile(self.calibration_scores, 1 - alpha)
        else:
            q = norm.ppf(1 - alpha/2)  # Fallback to normal
            
        lower = y_hat - q * sigma_hat
        upper = y_hat + q * sigma_hat
        
        return lower, upper, alpha
    
    def update(self, y_true, y_hat, sigma_hat):
        # Оновлення калібрувальних скорів
        score = np.abs(y_true - y_hat) / sigma_hat
        self.calibration_scores.append(score)
```

#### 2.2 DRO-ES Implementation
```python
# certification/dro_es.py
class DRO_ES:
    def __init__(self, alpha=0.05, eps_base=0.1):
        self.alpha = alpha
        self.eps_base = eps_base
        
    def optimize(self, scenarios, regime_z, aci):
        n, d = scenarios.shape
        
        # Режимно-залежний радіус
        eps = self._compute_eps(regime_z, aci)
        
        # CVX optimization
        w = cp.Variable(d)
        t = cp.Variable()
        xi = cp.Variable(n, nonneg=True)
        
        # Portfolio returns (negative for losses)
        returns = scenarios @ w
        
        # Constraints
        constraints = [
            xi >= -returns - t,
            cp.norm(w, 2) <= 1,  # Risk budget
            cp.sum(w) == 1,      # Full investment
            w >= -0.2,           # Short limit
            w <= 0.5             # Concentration limit
        ]
        
        # Objective: CVaR + Wasserstein penalty
        obj = cp.Minimize(
            t + (1/(self.alpha * n)) * cp.sum(xi) + 
            eps * cp.norm(w, 2)
        )
        
        prob = cp.Problem(obj, constraints)
        prob.solve(solver=cp.ECOS, verbose=False)
        
        return w.value, t.value
    
    def _compute_eps(self, regime_z, aci):
        # Більший радіус у нестабільних режимах
        base = self.eps_base
        
        if self._is_transition(regime_z):
            base *= 1.5
            
        base *= (1 + 0.2 * min(aci, 2.0))
        
        return base
```

#### 2.3 Kappa and Kappa+ Calculators
```python
# certification/uncertainty.py
class UncertaintyMetrics:
    def __init__(self, gamma=0.7):
        self.gamma = gamma
        self.bcc_tracker = BCCTracker()
        
    def compute_kappa(self, z, router_probs, pi_width, posterior):
        # Компоненти невизначеності
        state_u = torch.std(z).item()
        model_u = -torch.sum(router_probs * torch.log(router_probs + 1e-8)).item()
        forecast_u = pi_width / (posterior['sigma'] + 1e-8)
        
        # Зважена комбінація
        kappa = 0.4 * state_u + 0.3 * model_u + 0.3 * forecast_u
        
        return np.clip(kappa, 0, 1)
    
    def compute_kappa_plus(self, kappa, lower, upper, y_true=None):
        # Оновлення BCC якщо є ground truth
        if y_true is not None:
            self.bcc_tracker.update(lower, upper, y_true)
            
        bcc = self.bcc_tracker.get_score()
        
        # Blend
        kappa_plus = self.gamma * kappa + (1 - self.gamma) * (1 - bcc)
        
        return np.clip(kappa_plus, 0, 1)
```

### **PHASE 3: Integration & Testing**

#### 3.1 Main Trading Loop
```python
# trading/main_loop.py
class TradingSystem:
    def __init__(self, config):
        self.teacher = NFSDE.load(config.teacher_path)
        self.student = DSSM.load(config.student_path)
        self.router = RegimeRouter.load(config.router_path)
        self.icp = DynamicICP(config.alpha_base)
        self.dro = DRO_ES(config.es_alpha)
        self.uncertainty = UncertaintyMetrics(config.gamma)
        
        self.latency_budget = config.max_latency_ms
        self.position = None
        
    @torch.no_grad()
    def predict(self, market_data):
        start = time.perf_counter()
        
        # Feature extraction (5ms budget)
        features = self.extract_features(market_data)
        
        # Regime detection (10ms budget)
        regime_probs, regime_logits = self.router(features)
        regime = torch.argmax(regime_probs)
        
        # Student inference (30ms budget)
        _, z = self.student(features)
        y_hat, sigma_hat = self.student.decode(z)
        
        # ACI calculation (5ms budget)
        aci = self.compute_aci(z, regime_probs)
        
        # Certification (20ms budget)
        lower, upper, alpha = self.icp.predict_interval(
            y_hat, sigma_hat, z, aci
        )
        
        # Uncertainty (10ms budget)
        kappa = self.uncertainty.compute_kappa(
            z, regime_probs, upper - lower, 
            {'mu': y_hat, 'sigma': sigma_hat}
        )
        kappa_plus = self.uncertainty.compute_kappa_plus(
            kappa, lower, upper
        )
        
        # Portfolio optimization (15ms budget)
        if self._should_rebalance(kappa_plus):
            scenarios = self.generate_scenarios(z, regime)
            weights, cvar = self.dro.optimize(scenarios, regime, aci)
        else:
            weights = self.position
            
        # Latency check (5ms buffer)
        elapsed_ms = (time.perf_counter() - start) * 1000
        assert elapsed_ms < self.latency_budget, f"Latency {elapsed_ms:.1f}ms exceeded budget"
        
        return {
            'forecast': y_hat,
            'interval': (lower, upper),
            'weights': weights,
            'kappa_plus': kappa_plus,
            'regime': regime,
            'aci': aci,
            'latency_ms': elapsed_ms
        }
```

#### 3.2 Backtesting Framework
```python
# testing/backtest.py
class Backtester:
    def __init__(self, system, data):
        self.system = system
        self.data = data
        self.results = {
            'returns': [],
            'positions': [],
            'metrics': [],
            'coverage': []
        }
        
    def run(self, start_date, end_date):
        for timestamp, market_data in self.data.iter_range(start_date, end_date):
            # Prediction
            pred = self.system.predict(market_data)
            
            # Execute trade
            position = self.execute_trade(pred['weights'], market_data)
            
            # Calculate PnL
            if len(self.results['positions']) > 0:
                prev_pos = self.results['positions'][-1]
                returns = self.calculate_returns(prev_pos, position, market_data)
                self.results['returns'].append(returns)
            
            # Track metrics
            self.results['positions'].append(position)
            self.results['metrics'].append(pred)
            
            # Validate coverage
            next_price = self.data.get_next_price(timestamp)
            in_interval = pred['interval'][0] <= next_price <= pred['interval'][1]
            self.results['coverage'].append(in_interval)
            
        return self.compute_statistics()
    
    def compute_statistics(self):
        returns = np.array(self.results['returns'])
        coverage = np.mean(self.results['coverage'])
        
        stats = {
            'sharpe': np.sqrt(252) * returns.mean() / returns.std(),
            'sortino': np.sqrt(252) * returns.mean() / returns[returns < 0].std(),
            'max_dd': self.max_drawdown(returns),
            'cvar_95': np.percentile(returns, 5),
            'coverage': coverage,
            'avg_latency': np.mean([m['latency_ms'] for m in self.results['metrics']])
        }
        
        return stats
```

### **PHASE 4: API & Monitoring**

#### 4.1 FastAPI Service
```python
# api/service.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import asyncio

app = FastAPI(title="AURORA Trading API", version="1.2")

class PredictionRequest(BaseModel):
    symbol: str
    timeframe: str
    features: list[float]
    
class PredictionResponse(BaseModel):
    forecast: float
    interval_lower: float
    interval_upper: float
    weights: list[float]
    kappa_plus: float
    regime: str
    latency_ms: float

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    try:
        # Timeout wrapper
        result = await asyncio.wait_for(
            trading_system.predict_async(request.features),
            timeout=0.1  # 100ms timeout
        )
        
        return PredictionResponse(**result)
        
    except asyncio.TimeoutError:
        raise HTTPException(status_code=503, detail="Prediction timeout")
    except Exception as e:
        logger.error(f"Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
async def health():
    checks = {
        'model_loaded': trading_system.is_loaded(),
        'latency_ok': trading_system.avg_latency < 100,
        'memory_ok': get_memory_usage() < 0.9,
        'gpu_ok': torch.cuda.is_available()
    }
    
    if all(checks.values()):
        return {"status": "healthy", "checks": checks}
    else:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "checks": checks})
```

#### 4.2 Monitoring Setup
```yaml
# monitoring/prometheus.yml
scrape_configs:
  - job_name: 'aurora'
    static_configs:
      - targets: ['localhost:8000']
    metrics_path: '/metrics'
    scrape_interval: 5s

# Custom metrics to track
metrics:
  - aurora_prediction_latency_ms
  - aurora_kappa_plus
  - aurora_coverage_rate
  - aurora_regime_distribution
  - aurora_aci_value
  - aurora_portfolio_weights
  - aurora_pnl_cumulative
  - aurora_drawdown_current
  - aurora_sharpe_rolling
  - aurora_es_violations
```

```python
# monitoring/metrics.py
from prometheus_client import Histogram, Gauge, Counter

# Метрики
latency_histogram = Histogram(
    'aurora_prediction_latency_ms',
    'Prediction latency in milliseconds',
    buckets=[10, 25, 50, 75, 100, 150, 200, 500]
)

kappa_gauge = Gauge(
    'aurora_kappa_plus',
    'Current kappa plus uncertainty metric'
)

coverage_rate = Gauge(
    'aurora_coverage_rate',
    'Rolling coverage rate of prediction intervals'
)

es_violations = Counter(
    'aurora_es_violations',
    'Number of ES threshold violations'
)

# Декоратор для трекінгу
def track_metrics(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        
        try:
            result = func(*args, **kwargs)
            
            # Update metrics
            latency_ms = (time.perf_counter() - start) * 1000
            latency_histogram.observe(latency_ms)
            
            if 'kappa_plus' in result:
                kappa_gauge.set(result['kappa_plus'])
                
            return result
            
        except Exception as e:
            error_counter.inc()
            raise
            
    return wrapper
```

---

## IV. INTEGRATION MAP

### Data Flow Architecture
```
[Market Data Sources]
    ↓
[Data Ingester] → [Feature Pipeline] → [Buffer Queue]
    ↓                                      ↓
[Historical DB]                    [Real-time Stream]
    ↓                                      ↓
[Teacher NFSDE] ←→ [Distillation] → [Student DSSM]
                                           ↓
                              [Router] → [Regime Detection]
                                           ↓
                                    [ICP Certification]
                                           ↓
                                      [DRO-ES Opt]
                                           ↓
                                    [Trading Signal]
                                           ↓
                                 [Execution Engine]
```

### API Endpoints
```
POST /predict          → Real-time prediction
GET  /health          → Health check
GET  /metrics         → Prometheus metrics
POST /backtest        → Run backtest
GET  /model/info      → Model metadata
POST /model/reload    → Hot reload weights
GET  /regime/current  → Current regime
POST /alert/config    → Configure alerts
```

### External Integrations
```python
# integrations/connectors.py
CONNECTORS = {
    'market_data': {
        'binance': {'api_key': 'vault:binance_key', 'ws_endpoint': 'wss://stream.binance.com'},
        'polygon': {'api_key': 'vault:polygon_key', 'rest_endpoint': 'https://api.polygon.io'}
    },
    'execution': {
        'ib': {'gateway': 'localhost:4001', 'client_id': 1},
        'alpaca': {'api_key': 'vault:alpaca_key', 'endpoint': 'https://api.alpaca.markets'}
    },
    'monitoring': {
        'prometheus': {'port': 9090},
        'grafana': {'port': 3000},
        'alertmanager': {'port': 9093}
    }
}
```

---

## V. ACCEPTANCE CRITERIA

### Phase 0 Criteria
- [ ] GPU instances provisioned and accessible
- [ ] CUDA/cuDNN installed and verified
- [x] Data pipeline fetches last 2 years OHLCV *(ingester + gap filling + feature set)*
- [x] CI/CD runs unit tests in < 5 min *(workflow проходить, coverage ≥70%)*
- [x] Monitoring dashboard shows system metrics *(Prometheus + базовий Grafana, додані gating метрики)*

### Phase 1 Criteria  
- [ ] NFSDE generates trajectories with H ∈ [0.3, 0.7]
- [ ] DSSM ELBO converges to < 100 after 50 epochs
- [ ] Router ECE ≤ 0.05 on validation set
- [ ] Teacher-Student MMD < 0.1
- [ ] Tail statistics match within 10% (Kolmogorov-Smirnov)

### Phase 2 Criteria
- [x] ICP coverage ∈ [0.88, 0.92] for α=0.1 *(AdaptiveICP стабілізувався; stream test)*
- [ ] DRO-ES optimization converges in < 50ms *(повний cvxpy ще не вбудований)*
- [x] κ+ ∈ [0.2, 0.8] on normal market conditions *(спостережено в реплеях/тестах)*
- [ ] TVF 2.0 correctly rejects 90% of bad domains *(не інтегровано)*

### Phase 3 Criteria
- [ ] End-to-end latency < 100ms (p99)
- [ ] Backtest Sharpe ≥ baseline + 0.3
- [ ] Backtest Sortino ≥ baseline + 0.3  
- [ ] CVaR(95%) ≤ 10%
- [ ] Coverage rate ≥ 89%

### Phase 4 Criteria
- [ ] 14 days shadow with no critical errors
- [ ] Daily Sharpe variation < 0.5
- [ ] No ES violations > 3 consecutive days
- [ ] κ+ stability (std < 0.1 over 24h)
- [ ] Regime detection accuracy > 85%

### Phase 5 Criteria
- [ ] Canary 10% shows no degradation vs shadow
- [ ] Full deployment maintains SLA for 48h
- [ ] Rollback tested and < 2 min
- [ ] Alerts fire correctly on test scenarios
- [ ] PnL positive after fees

---

## VI. RISK & MITIGATION

### Technical Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Latency > 100ms** | Medium | High | Pre-compute features, model quantization, caching |
| **Model divergence** | Low | Critical | Gradient clipping, learning rate scheduling, early stopping |
| **Data gaps/errors** | Medium | Medium | Gap detection, interpolation, fallback to last known good |
| **GPU OOM** | Low | High | Batch size adaptation, gradient accumulation, model pruning |
| **Network failures** | Medium | Medium | Circuit breakers, retries with backoff, local cache |

### Business Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Regime misclassification** | Medium | High | Conservative position sizing on low confidence |
| **Tail event beyond model** | Low | Critical | Hard stop-loss, position limits, kill switch |
| **Regulatory changes** | Low | Medium | Parameterized compliance rules, audit logs |
| **Market microstructure shift** | Medium | Medium | Online adaptation, A/B testing, gradual rollout |

### Operational Risks

| Risk | Probability | Impact | Mitigation |
|------|------------|--------|------------|
| **Model staleness** | High | Medium | Scheduled retraining, drift detection, automated rollback |
| **Alert fatigue** | High | Low | Alert prioritization, aggregation, smart routing |
| **Key person dependency** | Medium | High | Documentation, pair programming, knowledge sharing |
| **Infrastructure costs** | Medium | Low | Spot instances for training, resource autoscaling |

### Fallback Procedures
```python
# risk/fallback.py
class FallbackController:
    def __init__(self):
        self.triggers = {
            'latency': lambda m: m['latency_ms'] > 150,
            'kappa': lambda m: m['kappa_plus'] > 0.9,
            'coverage': lambda m: m['coverage'] < 0.8,
            'drawdown': lambda m: m['drawdown'] > 0.15
        }
        
    def check_triggers(self, metrics):
        for name, condition in self.triggers.items():
            if condition(metrics):
                return self.execute_fallback(name)
        return None
        
    def execute_fallback(self, trigger_name):
        actions = {
            'latency': self.switch_to_simple_model,
            'kappa': self.reduce_position_size,
            'coverage': self.widen_intervals,
            'drawdown': self.emergency_close_positions
        }
        return actions[trigger_name]()
```

---

## VII. PRIORITY GUIDE

### Critical Path (MVP - Must Have)
1. **DSSM Student** - Core prediction engine
2. **ICP Basic** - Minimum viable certification  
3. **Simple Router** - AR/GARCH detection only
4. **Basic API** - /predict endpoint
5. **Latency < 100ms** - Hard requirement

### Important (Should Have)
1. **NFSDE Teacher** - Better accuracy
2. **DRO-ES** - Robust portfolio optimization
3. **Dynamic α** - Adaptive intervals
4. **Full Router** - All three regimes
5. **Monitoring** - Prometheus/Grafana

### Nice to Have (Could Have)
1. **κ+** - Advanced uncertainty
2. **TVF 2.0** - Transfer validation
3. **Hawkes jumps** - Complex dynamics
4. **Shadow mode** - Pre-production testing
5. **Alert system** - Proactive monitoring

### Future Enhancements (Won't Have Now)
1. **Multi-asset** - Cross-asset strategies
2. **Options integration** - Derivatives
3. **HFT mode** - Sub-millisecond
4. **Cloud-native** - Kubernetes deployment
5. **AutoML** - Automated hyperparameter tuning

### Implementation Order
```
Week 1: Infrastructure + DSSM core
Week 2: ICP + Simple Router + API
Week 3: Integration + Latency optimization
Week 4: NFSDE + DRO-ES + Monitoring
Week 5: Backtest + Parameter tuning
Week 6-7: Shadow trading
Week 8: Production launch
```

### Decision Matrix
```python
# Priority scoring
def priority_score(feature):
    weights = {
        'business_value': 0.4,
        'technical_risk': -0.2,
        'implementation_effort': -0.2,
        'dependency_count': -0.1,
        'operational_impact': 0.1
    }
    
    score = sum(weights[k] * feature[k] for k in weights)
    return score

features = [
    {'name': 'DSSM', 'business_value': 10, 'technical_risk': 3, ...},
    {'name': 'NFSDE', 'business_value': 7, 'technical_risk': 8, ...},
    # ...
]

sorted_features = sorted(features, key=priority_score, reverse=True)
```

---

## ДОДАТОК A: Команди швидкого старту

```bash
# Clone and setup
git clone https://github.com/org/aurora-v1.2
cd aurora-v1.2
make setup-env

# Install dependencies
pip install -r requirements.txt
pip install -r requirements-dev.txt

# Download data
python scripts/download_historical.py --symbols BTC,ETH --years 2

# Train models
python train_teacher.py --config configs/nfsde.yaml
python train_student.py --config configs/dssm.yaml --teacher checkpoints/nfsde_best.pt

# Run backtest
python backtest.py --model checkpoints/dssm_best.pt --start 2023-01-01 --end 2023-12-31

# Start service
uvicorn api.service:app --host 0.0.0.0 --port 8000 --workers 4

# Monitor
docker-compose up -d prometheus grafana
open http://localhost:3000/dashboards/aurora
```

---

## ДОДАТОК B: Конфігураційні файли

```yaml
# configs/production.yaml
model:
  teacher:
    type: NFSDE
    d_state: 16
    d_latent: 32
    H_blocks: 128
    checkpoint: s3://models/nfsde_v1.2.pt
    
  student:
    type: DSSM
    d_obs: 20
    d_latent: 32
    d_hidden: 512
    checkpoint: s3://models/dssm_v1.2.pt
    
  router:
    num_regimes: 3
    temperature: 1.2
    checkpoint: s3://models/router_v1.2.pt

certification:
  icp:
    alpha_base: 0.1
    window: 1000
    
  dro:
    alpha: 0.05
    eps_base: 0.1
    
  uncertainty:
    gamma: 0.7
    
trading:
  max_latency_ms: 100
  position_limit: 0.5
  stop_loss: 0.05
  
monitoring:
  prometheus_port: 9090
  grafana_port: 3000
  alert_email: ops@company.com
```

---

**END OF IMPLEMENTATION PLAN**
