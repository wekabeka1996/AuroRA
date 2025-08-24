
# WiseScalp v0.3 — Aurora Integration Patch

This patch adds a **non-destructive** Aurora pre-trade gate integration:
- `integrations/aurora_gate.py` — minimal HTTP client
- `runner/run_live_aurora.py` — live loop that calls `/pretrade/check` before entries and `/posttrade/log` on exits
- `configs/default.aurora.yaml` — example config with the `aurora` section
- `scripts/run_live_aurora.py` — CLI wrapper

## How to apply

1. Unzip this patch on top of your WiseScalp v0.3 repo (keeps originals intact).
2. Ensure Aurora service is reachable (e.g., `http://127.0.0.1:8037`).
3. Export testnet keys if needed:
   ```bash
   export BINANCE_API_KEY=... 
   export BINANCE_API_SECRET=...
   export AURORA_MODE=shadow   # or paper/prod
   ```
4. Run:
   ```bash
   python -m scripts.run_live_aurora  # uses configs/default.yaml by default
   # or
   python -m scripts.run_live_aurora configs/default.aurora.yaml
   ```

## Notes

- In **shadow/paper** modes, if Aurora is unavailable, the client **fails open** (logs reason).
- In **prod**, set `aurora.mode: prod` and run Aurora with **hard gating**; the bot will respect `allow=false` and `hard_gate=true`.
- Order sizing can be reduced by Aurora via `max_qty`. The example loop also applies a `cooldown_ms` from Aurora.
- The loop simulates a simple position and calls `/posttrade/log` on exits to report synthetic PnL.

Generated: 2025-08-24T00:46:03.608286Z
