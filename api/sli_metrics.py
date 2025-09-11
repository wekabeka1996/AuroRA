from __future__ import annotations

from prometheus_client import Counter


class IdemMetrics:
    """Prometheus counters for idempotency guard.

    All counters are optional-use: if registry wiring fails, construction can be skipped.
    """

    def __init__(self, registry) -> None:
        # Outcome-labelled check counter
        self.check_total = Counter(
            "aurora_idem_check_total",
            "Idempotency pre-submit checks",
            ["outcome"],  # outcome in {store, hit, conflict}
            registry=registry,
        )
        self.update_total = Counter(
            "aurora_idem_update_total",
            "Idempotency status updates",
            ["status"],  # status values (PENDING, ACK, ERROR, ...)
            registry=registry,
        )
        self.dup_submit_total = Counter(
            "aurora_idem_duplicate_submit_total",
            "Duplicate submit attempts blocked by idempotency",
            registry=registry,
        )

    # convenience helpers
    def inc_check(self, outcome: str) -> None:
        try:
            self.check_total.labels(outcome=outcome).inc()
        except Exception:
            pass

    def inc_update(self, status: str) -> None:
        try:
            self.update_total.labels(status=status).inc()
        except Exception:
            pass

    def inc_dup_submit(self) -> None:
        try:
            self.dup_submit_total.inc()
        except Exception:
            pass


__all__ = ["IdemMetrics"]
