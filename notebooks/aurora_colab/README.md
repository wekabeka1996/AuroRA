Aurora Colab Notebook

This folder contains a Colab-ready notebook to:

- Load SSOT config from `configs/schema.json` and `configs/default.toml`.
- Ingest XAI/TCA/Risk logs (`*.jsonl.gz`) and parse into pandas DataFrames.
- Compute order-level, session-level, TCA, and Risk metrics.
- Visualize distributions (IS, fill_ratio, deny codes, CVaR).
- Manage profiles (`local_low`, `local_mid`, `local_high`) and materialize effective configs.
- Integrate with Optuna for multi-objective tuning (maximize EΠ_after_TCA, minimize CVaR95) and render Pareto frontier.
- Run a simple OOS check by evaluating top-5 configs on another day/symbol logs.

Artifacts created when running the notebook:

- `reports/optuna_frontier.png` — Pareto front plot
- `reports/optuna_best_local.json` — Top configs from Optuna
- `reports/aurora_suggested.toml` — Frozen suggestion config

Usage (Colab):

1) Open the notebook `Aurora_SSOT_XAI_Optuna.ipynb` in Google Colab.
2) Run the setup cells to install dependencies (Colab environment only).
3) Upload or point the notebook to your `*.jsonl.gz` logs.
4) Select a profile, run Optuna, and export artifacts.

Notes:

- The notebook auto-detects the project root if run from repository root. You can override the path in the Setup cell.
- Metrics calculation is resilient to missing fields; where raw components are absent, it falls back to proxies.
- No secrets are required to run; only local files.

Included tunables/overlays:

- sizing: `sizing.limits.max_notional_usd` (profile `sizing_max_position_usd` maps here)
- universe: `universe.ranking.top_n`, `execution.router.spread_limit_bps` (profile keys `universe_top_n`, `universe_spread_bps_limit`)
- reward: `reward.ttl_minutes` (profile key `reward_ttl_minutes`)

Interactive controls (in Colab):

- `Profile` dropdown: choose `local_low`/`local_mid`/`local_high` overlay.
- Sliders: `top_n`, `TTL (min)`, `max_notional`, `spread_bps`.
- Numeric inputs: `latency_ms`, `leverage`.
