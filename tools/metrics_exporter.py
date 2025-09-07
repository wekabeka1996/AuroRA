# -*- coding: utf-8 -*-
"""Aurora Prometheus exporter: SLI/SLO-critical metrics.

Usage:
    from tools.metrics_exporter import METRICS
    METRICS.start_http(port=int(os.getenv("METRICS_PORT", 9000)))
    METRICS.sse.on_connect()
    METRICS.policy.on_decision(allowed=True, symbol="SOON")
    METRICS.exec.observe_latency_ms(12.3)
    METRICS.cb.set_state("CLOSED")
    METRICS.calibration.update(ece=0.032, brier=0.15, logloss=0.59)
    METRICS.risk.cvar_breach("SOON")  # якщо спіймано порушення гейта
"""
import time
from typing import Optional
from prometheus_client import (
    CollectorRegistry, Counter, Gauge, Histogram, Summary, start_http_server
)


class _SSE:
    def __init__(self, reg: CollectorRegistry):
        self.clients = Gauge(
            "sse_clients_connected", "Active SSE clients", registry=reg
        )
        self.attempted = Counter(
            "sse_events_attempted_total", "SSE events attempted to send", registry=reg
        )
        self.sent = Counter(
            "sse_events_sent_total", "SSE events successfully sent", registry=reg
        )
        self.dropped = Counter(
            "sse_events_dropped_total", "SSE events dropped/failed", registry=reg
        )
        self.reconnects = Counter(
            "sse_reconnects_total", "Client reconnects observed", registry=reg
        )

    # Hooks
    def on_connect(self):
        self.clients.inc()

    def on_disconnect(self):
        self.clients.dec()

    def on_attempt(self, n: int = 1):
        self.attempted.inc(n)

    def on_sent(self, n: int = 1):
        self.sent.inc(n)

    def on_drop(self, n: int = 1):
        self.dropped.inc(n)

    def on_reconnect(self, n: int = 1):
        self.reconnects.inc(n)


class _Policy:
    def __init__(self, reg: CollectorRegistry):
        self.considered = Counter(
            "policy_considered_total", "Decisions evaluated", registry=reg
        )
        self.allowed = Counter(
            "policy_allowed_total", "Allowed decisions", ["symbol"], registry=reg
        )
        self.denied = Counter(
            "policy_denied_total", "Denied decisions", ["symbol", "why"], registry=reg
        )

    def on_decision(self, allowed: bool, symbol: str, why: str = ""):  # map WHY-код
        self.considered.inc()
        if allowed:
            self.allowed.labels(symbol=symbol).inc()
        else:
            self.denied.labels(symbol=symbol, why=why or "unspecified").inc()


class _Exec:
    def __init__(self, reg: CollectorRegistry):
        self.latency = Histogram(
            "exec_latency_ms", "Order round-trip latency (ms)",
            buckets=(1,2,5,10,20,50,100,200,300,500,750,1000,1500,2000,3000,5000),
            registry=reg
        )
        self.slippage_bps = Summary(
            "tca_slippage_bps", "Observed slippage (bps)", registry=reg
        )
        self.fees_bps = Summary(
            "tca_fees_bps", "Fees (bps)", registry=reg
        )
        self.adverse_bps = Summary(
            "tca_adverse_bps", "Adverse selection (bps)", registry=reg
        )

    def observe_latency_ms(self, v: float):
        self.latency.observe(v)

    def observe_tca(self, slippage_bps: float, fees_bps: float, adverse_bps: float):
        self.slippage_bps.observe(slippage_bps)
        self.fees_bps.observe(fees_bps)
        self.adverse_bps.observe(adverse_bps)


class _Calibration:
    def __init__(self, reg: CollectorRegistry):
        self.ece = Gauge("calibration_ece", "Expected Calibration Error", registry=reg)
        self.brier = Gauge("calibration_brier", "Brier score", registry=reg)
        self.logloss = Gauge("calibration_logloss", "LogLoss", registry=reg)

    def update(self, *, ece: Optional[float] = None, brier: Optional[float] = None,
               logloss: Optional[float] = None):
        if ece is not None: self.ece.set(ece)
        if brier is not None: self.brier.set(brier)
        if logloss is not None: self.logloss.set(logloss)


class _CB:
    _MAP = {"CLOSED": 0, "HALF_OPEN": 1, "OPEN": 2}

    def __init__(self, reg: CollectorRegistry):
        self.state = Gauge("circuit_breaker_state", "0=CLOSED,1=HALF_OPEN,2=OPEN", registry=reg)

    def set_state(self, state: str):
        self.state.set(self._MAP.get(state.upper(), 0))


class _Risk:
    def __init__(self, reg: CollectorRegistry):
        self._cvar_breach_counter = Counter(
            "risk_cvar_breach_total", "CVaR gate breaches", ["symbol"], registry=reg
        )

    def cvar_breach(self, symbol: str):
        self._cvar_breach_counter.labels(symbol=symbol).inc()


class _Governance:
    def __init__(self, reg: CollectorRegistry):
        # Counter per governance deny reason
        self.denies = Counter(
            "governance_denies_total", "Governance denies by reason code", ["reason"], registry=reg
        )
        # Remaining alpha gauge per test id
        self.alpha_remaining_g = Gauge(
            "governance_alpha_remaining", "Remaining alpha budget per test id", ["test_id"], registry=reg
        )

    def on_deny(self, reason_code: str):
        self.denies.labels(reason=reason_code or "UNKNOWN").inc()

    def alpha_remaining(self, test_id: str, remaining: float):
        try:
            self.alpha_remaining_g.labels(test_id=test_id).set(float(remaining))
        except Exception:
            # Defensive: ignore label errors / bad conversion
            pass


class _Metrics:
    def __init__(self):
        self.reg = CollectorRegistry()
        self.sse = _SSE(self.reg)
        self.policy = _Policy(self.reg)
        self.exec = _Exec(self.reg)
        self.calibration = _Calibration(self.reg)
        self.cb = _CB(self.reg)
        self.risk = _Risk(self.reg)
        self.governance = _Governance(self.reg)
        self._started = False

    def start_http(self, port: int = 9000, addr: str = "0.0.0.0"):
        if not self._started:
            start_http_server(port, addr=addr, registry=self.reg)
            self._started = True
        return self


METRICS = _Metrics()

# Alias for backwards compatibility
AuroraMetricsExporter = _Metrics