Idempotency Backend Selection
============================

Aurora supports pluggable backends for the idempotency store used in execution and tests.

- Default: in-memory (process-local), TTL-based.
- Persistent: SQLite, enabled via environment variables.

Environment variables:
- AURORA_IDEM_BACKEND: "memory" (default) or "sqlite".
- AURORA_IDEM_SQLITE_PATH: path to SQLite file (default: data/idem.db).

API is stable: import IdempotencyStore from core.execution.idempotency and construct as usual.

Example (bash):
  AURORA_IDEM_BACKEND=sqlite AURORA_IDEM_SQLITE_PATH=./data/idem.db python -m pytest -q tests/unit/test_idem_sqlite_backend.py
