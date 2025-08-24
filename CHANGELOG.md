# Changelog

## v1.0.0-canary.1

- Pretrade gating finalized: latency → TRAP → expected_return ↔ slippage (feature-flag) → risk caps → SPRT → spread
- TRAP v2 (robust z-score + score), rollback, observability
- Expected-return gate via calibrator; slippage guard with eta fraction of b
- Health latency p95 guard with WARN→COOL_OFF→HALT and OPS endpoints
- Risk caps: dd_day_pct, max_concurrent, size_scale; OPS snapshot/set
- Strict Pydantic API contracts; /health includes version and order_profile
- Canary summary and summary_gate with deterministic rules; harness auto-cooloff
- CI: artifacts upload (latency CSV, escalations flow, summary MD, risk_denies.csv); nightly perf job
