# Definition of Done — CLI Unification (R1)

Status legend: [x] Done, [ ] Deferred

- [x] Unified Python CLI (Typer) at `tools/auroractl.py` replacing .ps1 scripts
- [x] Environment loaded via `.env` only; defaults in `core/env.py`
- [x] Wallet audit command: balances + live withdrawals status/limits; writes `artifacts/wallet_check.json`; non‑zero exit on issues
- [x] Order logging split into 3 JSONL streams (success/failed/denied) with rotation; wired in `api/service.py`
- [x] Metrics aggregation: parse `logs/events.jsonl`, write `reports/summary_gate_status.json`, `artifacts/canary_summary.md`, `artifacts/latency_p95_timeseries.csv`; optional Pushgateway
- [x] Readiness audit baseline present (`tools/ready_audit.py`); docs updated; exit codes consistent
- [x] Tests covering env, wallet_check (mocked ccxt), metrics p95 CSV, order_logger, and readiness audit
- [x] README updated with CLI mapping and exit codes; Makefile helpers added
- [x] VS Code tasks validated; targeted pytest tasks pass locally
- [x] Journal entry added in `docs/agent_journal.md`
- [ ] Deeper readiness checks (runtime fail‑closed verification, DRY_RUN dry‑cycle): planned in follow‑ups
- [ ] Ensure all runner paths use new OrderLoggers: tracked for v4‑min integration

Notes:
- Windows users can run commands via `python tools/auroractl.py ...` (Makefile optional).
- Set `PUSHGATEWAY_URL` to enable metrics push.
