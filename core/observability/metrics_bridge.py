# -*- coding: utf-8 -*-
"""Aurora Metrics Bridge.

This module provides a stable interface for metrics collection across Aurora components.
It acts as a thin layer that exposes consistent hook names for incrementing counters,
observing values, and setting gauges without coupling to specific metrics implementations.

Usage:
    from core.observability.metrics_bridge import METRICS

    # SSE metrics
    METRICS.sse.on_connect()
    METRICS.sse.on_attempt(count=5)
    METRICS.sse.on_sent(count=4)
    METRICS.sse.on_drop(count=1)
    METRICS.sse.on_reconnect()

    # Policy metrics
    METRICS.policy.on_decision(allowed=True, symbol="SOON")
    METRICS.policy.on_decision(allowed=False, symbol="SOON", why="spread_too_wide")

    # Execution metrics
    METRICS.exec.observe_latency_ms(123.45)
    METRICS.exec.observe_tca(slippage_bps=1.2, fees_bps=0.8, adverse_bps=0.5)

    # Calibration metrics
    METRICS.calibration.update(ece=0.032, brier=0.15, logloss=0.59)

    # Circuit breaker metrics
    METRICS.cb.set_state("CLOSED")  # CLOSED, HALF_OPEN, OPEN

    # Risk metrics
    METRICS.risk.cvar_breach("SOON")
"""

import os
from typing import Optional, Protocol
from abc import ABC, abstractmethod


class SSEMetrics(Protocol):
    """Protocol for SSE-related metrics."""
    def on_connect(self) -> None: ...
    def on_disconnect(self) -> None: ...
    def on_attempt(self, n: int = 1) -> None: ...
    def on_sent(self, n: int = 1) -> None: ...
    def on_drop(self, n: int = 1) -> None: ...
    def on_reconnect(self, n: int = 1) -> None: ...


class PolicyMetrics(Protocol):
    """Protocol for policy decision metrics."""
    def on_decision(self, allowed: bool, symbol: str, why: str = "") -> None: ...


class ExecMetrics(Protocol):
    """Protocol for execution metrics."""
    def observe_latency_ms(self, v: float) -> None: ...
    def observe_tca(self, slippage_bps: float, fees_bps: float, adverse_bps: float) -> None: ...


class CalibrationMetrics(Protocol):
    """Protocol for calibration metrics."""
    def update(self, *, ece: Optional[float] = None, brier: Optional[float] = None,
               logloss: Optional[float] = None) -> None: ...


class CBMetrics(Protocol):
    """Protocol for circuit breaker metrics."""
    def set_state(self, state: str) -> None: ...


class RiskMetrics(Protocol):
    """Protocol for risk management metrics."""
    def cvar_breach(self, symbol: str) -> None: ...


class GovernanceMetrics(Protocol):
        """Protocol for governance/alpha ledger metrics.

        Exposes:
            - on_deny(reason_code): increment deny counter per reason
            - alpha_remaining(test_id, remaining): gauge current remaining alpha for a token/test
        """
        def on_deny(self, reason_code: str) -> None: ...
        def alpha_remaining(self, test_id: str, remaining: float) -> None: ...


class MetricsProvider(Protocol):
    """Protocol for metrics provider implementation."""
    sse: SSEMetrics
    policy: PolicyMetrics
    exec: ExecMetrics
    calibration: CalibrationMetrics
    cb: CBMetrics
    risk: RiskMetrics
    governance: GovernanceMetrics

    def start_http(self, port: int = 9000, addr: str = "0.0.0.0") -> "MetricsProvider": ...


class NoOpMetrics:
    """No-operation metrics implementation for when metrics are disabled."""

    class _NoOpSSE:
        def on_connect(self) -> None: pass
        def on_disconnect(self) -> None: pass
        def on_attempt(self, n: int = 1) -> None: pass
        def on_sent(self, n: int = 1) -> None: pass
        def on_drop(self, n: int = 1) -> None: pass
        def on_reconnect(self, n: int = 1) -> None: pass

    class _NoOpPolicy:
        def on_decision(self, allowed: bool, symbol: str, why: str = "") -> None: pass

    class _NoOpExec:
        def observe_latency_ms(self, v: float) -> None: pass
        def observe_tca(self, slippage_bps: float, fees_bps: float, adverse_bps: float) -> None: pass

    class _NoOpCalibration:
        def update(self, *, ece: Optional[float] = None, brier: Optional[float] = None,
                   logloss: Optional[float] = None) -> None: pass

    class _NoOpCB:
        def set_state(self, state: str) -> None: pass

    class _NoOpRisk:
        def cvar_breach(self, symbol: str) -> None: pass

    class _NoOpGovernance:
        def on_deny(self, reason_code: str) -> None: pass
        def alpha_remaining(self, test_id: str, remaining: float) -> None: pass

    def __init__(self):
        self.sse = self._NoOpSSE()
        self.policy = self._NoOpPolicy()
        self.exec = self._NoOpExec()
        self.calibration = self._NoOpCalibration()
        self.cb = self._NoOpCB()
        self.risk = self._NoOpRisk()
        self.governance = self._NoOpGovernance()

    def start_http(self, port: int = 9000, addr: str = "0.0.0.0") -> "NoOpMetrics":
        return self


def _get_metrics_provider() -> MetricsProvider:
    """Get the configured metrics provider."""
    # Try to import Prometheus metrics exporter
    try:
        from tools.metrics_exporter import METRICS
        return METRICS
    except ImportError:
        # Fall back to no-op implementation
        return NoOpMetrics()


# Global metrics instance
METRICS: MetricsProvider = _get_metrics_provider()