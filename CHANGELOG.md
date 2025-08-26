# Changelog

## v0.4-beta — 2025-08-26

### Added
- Потік подій `ORDER.*` (dot-канон) з раннера/АПІ: SUBMIT/ACK/PARTIAL/FILL/REJECT/CANCEL.REQUEST/CANCEL.ACK/EXPIRE.
- `AckTracker` із фоновим скануванням (TTL=`AURORA_ACK_TTL_S`, period=`AURORA_ACK_SCAN_PERIOD_S`).
- Стаб CANCEL (`AURORA_CANCEL_STUB`, за замовчуванням `false`).
- `metrics_summary` до цільової схеми + підтримка `.jsonl.gz`.
- Prom-лічильники: `aurora_events_emitted_total{code}`, `orders_{filled,rejected,denied}_total`.

### Changed
- `AuroraEventLogger`: нормалізація тільки `ORDER_* → ORDER.*`, монотонний `ts_ns`, ідемпотентність.
- Нормалізатор помилок біржі: відомі коди → struct, інше → `"UNKNOWN"`.

### Fixed
- Інкремент `ORDERS_SUCCESS`/`ORDERS_*` прив’язаний до факту запису у `orders_*.jsonl`.
- Емісія `SPREAD_GUARD_TRIP` через новий емиттер.

### Ops
- `.env.example`: `AURORA_ACK_TTL_S=300`, `AURORA_ACK_SCAN_PERIOD_S=1`, `AURORA_CANCEL_STUB=false`, `AURORA_CANCEL_STUB_EVERY_TICKS=120`, `AURORA_LOG_RETENTION_DAYS=7`, `AURORA_LOG_ROTATE_MAX_MB=200`, `OPS_TOKEN` (+ alias `AURORA_OPS_TOKEN` з WARN).

### Tests
- `test_lifecycle_correlation.py`, `test_events_emission.py`, `test_events_rotation.py`,
  `test_metrics_summary.py`, `test_order_counters.py`,
  `test_ops_endpoints_auth.py::test_events_prom_counter_increments`,
  `test_late_ack_and_partial_cancel.py`.
