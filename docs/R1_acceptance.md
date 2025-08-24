## Pre-trade gate ordering (frozen)

Current order:

latency (threshold + p95) → TRAP → expected_return → slippage → risk caps → SPRT → spread

Switchable profile:

- YAML: `pretrade.order_profile` (default `er_before_slip`)
- ENV: `PRETRADE_ORDER_PROFILE` overrides YAML

Observability contract includes:

- `observability.reasons[]` (ordered reasons)
- `observability.risk{cfg,ctx}`
- `risk_scale` in response
# R1 Acceptance (Controlled Planning)

Минимальные критерии успешности (2 независимых прогона):

- **PASS == true** и отсутствие критичных safety‑violations.
- **R1_win_rate ≥ 0.55** (доля мостов с ΔJ > 0 после исполнения и онлайн‑оценки).
- **mean ΔJ > 0** по мостам, вошедшим в исполнение.
- **Δsurprisal_p95 (trimmed) ≤ 0**.
- **Latency p95 ≤ 1.2×** относительно R0 baseline.
- **ema(|Δτ|) ≤ tau_drift_limit** (из конфига r1.tau_drift_limit).
- В summary присутствуют блоки: `r1.bridges{p50,p90,positive_fraction_eps}`,
  `r1.blocks{two_signals_block_count, mi_guard_block_count, reachability_reject_count}`,
  `r1.tau_drift_ema`, `r1.tau_drift_ok`.

## Поля summary/r1

```jsonc
{
  "r1": {
    "bridges": {
      "count": 123,
      "positive_fraction_eps": 0.61,
      "mean": 0.0042,
      "p10": 0.0001,
      "p50": 0.0039,
      "p90": 0.0112,
      "width_p90_p10": 0.0111
    },
    "blocks": {
      "two_signals_block_count": 4,
      "mi_guard_block_count": 1,
      "reachability_reject_count": 2
    },
    "tau_drift_ema": 0.0123,
    "tau_drift_ok": true,
    "improvement_eps_reporting": 0.0005
  }
}
```

## Методика

1. `improvement` у моста — скаляр разницы целевой функции (например, ΔJ) или прокси.
2. Отбор статистик: p10/p50/p90 и ширина (robust dispersion) p90-p10.
3. Фильтр eps исключает «микро»-улучшения: считаем долю ≥ eps.
4. Блокировки и дрейф τ считываются из `blackbox.jsonl` событий (`policy_block`, `reachability_reject`, `tau_update`).
5. EMA(|Δτ|) с полужизнью `tau_drift_ema_halflife_s`; лимит `tau_drift_limit`.

## Follow‑up (необязательные расширения)
- Добавить trimmed mean/median абсолютных улучшений.
- Разделить мосты по типам (liquidity / latency / strategy).
- Визуализация распределений (p95 whiskers) для отчётов.
