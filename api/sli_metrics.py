from __future__ import annotations

from prometheus_client import Counter, Gauge, Histogram


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


class ExchangeMetrics:
    """Prometheus metrics for exchange operations with retry and circuit breaker."""

    def __init__(self, registry) -> None:
        # Retry metrics
        self.retry_total = Counter(
            "aurora_exchange_retry_total",
            "Total exchange retry attempts",
            ["exchange", "operation", "error_category"],
            registry=registry,
        )

        # Operation latency
        self.operation_latency = Histogram(
            "aurora_exchange_op_latency_ms",
            "Exchange operation latency in milliseconds",
            ["exchange", "operation", "status"],  # status: success|failure
            buckets=[1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000],
            registry=registry,
        )

        # Circuit breaker state
        self.cb_state = Gauge(
            "aurora_exchange_cb_state",
            "Circuit breaker state (0=CLOSED, 1=HALF_OPEN, 2=OPEN)",
            ["exchange"],
            registry=registry,
        )

        # Error classification
        self.error_total = Counter(
            "aurora_exchange_error_total",
            "Total exchange errors by category",
            ["exchange", "operation", "category", "severity"],
            registry=registry,
        )

    # Convenience helpers
    def inc_retry(self, exchange: str, operation: str, error_category: str) -> None:
        try:
            self.retry_total.labels(
                exchange=exchange, operation=operation, error_category=error_category
            ).inc()
        except Exception:
            pass

    def observe_latency(
        self, exchange: str, operation: str, status: str, latency_ms: float
    ) -> None:
        try:
            self.operation_latency.labels(
                exchange=exchange, operation=operation, status=status
            ).observe(latency_ms)
        except Exception:
            pass

    def set_cb_state(self, exchange: str, state_value: int) -> None:
        """Set circuit breaker state: 0=CLOSED, 1=HALF_OPEN, 2=OPEN"""
        try:
            self.cb_state.labels(exchange=exchange).set(state_value)
        except Exception:
            pass

    def inc_error(
        self, exchange: str, operation: str, category: str, severity: str
    ) -> None:
        try:
            self.error_total.labels(
                exchange=exchange,
                operation=operation,
                category=category,
                severity=severity,
            ).inc()
        except Exception:
            pass


__all__ = ["IdemMetrics", "ExchangeMetrics"]
