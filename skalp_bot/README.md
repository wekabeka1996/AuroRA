# WiseScalp v0.3 — OBI Live (Colab-ready)

Lightweight micro-scalping research stack with combined alpha (OBI + TFI + micro-price)
and basic risk management. Includes an L5 backtester notebook for Google Colab.

> This code is for research/education. You are responsible for any usage.
> Live trading is disabled by default (`dry_run: true`). Supply your own testnet keys via ENV if you enable it.

Structure:
```
core/      # signals, utils, simple backtest engine
exch/      # minimal CCXT adapter for Binance
risk/      # basic risk manager
runner/    # scripts to run live/sim
scripts/   # CLI wrappers
configs/   # YAML config
notebooks/ # L5 backtester (Colab)
```

Quick start (Colab):
1. Upload this zip or mount drive, then open `notebooks/WiseScalp_L5_backtester.ipynb`.
2. Run all cells — it will install minimal deps and run the synthetic backtest.
3. Adjust thresholds in the notebook or `configs/default.yaml` and re-run.

Minimal live (testnet/dry-run):
- Set env vars `BINANCE_API_KEY` and `BINANCE_API_SECRET` for testnet keys.
- Keep `dry_run: true` in `configs/default.yaml` unless you want to send testnet orders.
