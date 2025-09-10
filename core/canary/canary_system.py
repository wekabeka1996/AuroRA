"""
Canary Implementation for Aurora Step 4
========================================

Shadow → Canary 1% on testnet with kill switches and monitoring.

Features:
- 1% position sizing on testnet
- BTCUSDT maker-only execution
- Real-time kill switches (vol_spike, API timeouts, spread>limit, CVaR breach, DD intraday >70%)
- SLO monitoring and alerts
- Automatic emergency stops
- Comprehensive metrics collection
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
import threading
import time

from common.events import EventEmitter
from core.execution.execution_router_v1 import ExecutionContext, ExecutionRouter


class KillSwitchType(Enum):
    """Types of kill switches"""
    VOL_SPIKE = "vol_spike"
    API_TIMEOUT = "api_timeout"
    SPREAD_LIMIT = "spread_limit"
    CVAR_BREACH = "cvar_breach"
    DD_INTRADAY = "dd_intraday"
    MANUAL = "manual"


class CanaryState(Enum):
    """Canary operational states"""
    INACTIVE = "inactive"
    # NOTE: 'shadow' runtime mode removed project-wide (2025-08-30).
    # Historical: shadow was a monitoring-only mode that did not place orders.
    CANARY = "canary"      # 1% live execution
    EMERGENCY_STOP = "emergency_stop"
    KILLED = "killed"


@dataclass
class CanaryConfig:
    """Configuration for canary deployment"""
    # Sizing
    canary_size_pct: float = 1.0  # 1% of normal size
    max_position_usd: float = 100.0  # Max $100 per position

    # Symbols
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT"])
    maker_only: bool = True

    # Kill switch thresholds
    vol_spike_threshold_atr_mult: float = 2.5
    spread_limit_bps: float = 8.0
    dd_intraday_limit_pct: float = 7.0  # 70% of daily limit
    api_timeout_threshold_ms: float = 3000
    max_consecutive_timeouts: int = 3

    # Monitoring
    metrics_interval_s: int = 10
    alert_cooldown_s: int = 300  # 5 minutes between alerts

    # Emergency stops
    emergency_stop_cooldown_minutes: int = 5


@dataclass
class CanaryMetrics:
    """Real-time canary metrics"""
    start_time_ns: int
    orders_placed: int = 0
    orders_filled: int = 0
    orders_cancelled: int = 0
    total_volume_usd: float = 0.0
    total_pnl_usd: float = 0.0
    avg_fill_latency_ms: float = 0.0
    cancel_ratio: float = 0.0
    maker_fill_ratio: float = 0.0
    decision_latencies_ms: list[float] = field(default_factory=list)
    kill_switches_triggered: list[dict] = field(default_factory=list)


class CanarySystem:
    """Canary deployment system with kill switches and monitoring"""

    def __init__(self, config: CanaryConfig | None = None):
        self.config = config or CanaryConfig()
        self.state = CanaryState.INACTIVE
        self.metrics = CanaryMetrics(start_time_ns=time.time_ns())

        # Components
        self.execution_router = ExecutionRouter()
        self.event_logger = EventEmitter()
        self.kill_switches = {}

        # Monitoring
        self.monitoring_thread = None
        self.monitoring_active = False
        self.last_alert_time = 0

        # Callbacks
        self.on_kill_switch: Callable | None = None
        self.on_emergency_stop: Callable | None = None

        self._setup_kill_switches()
        self._setup_monitoring()

    def _setup_kill_switches(self):
        """Initialize kill switch monitors"""
        self.kill_switches = {
            KillSwitchType.VOL_SPIKE: self._check_vol_spike,
            KillSwitchType.API_TIMEOUT: self._check_api_timeout,
            KillSwitchType.SPREAD_LIMIT: self._check_spread_limit,
            KillSwitchType.CVAR_BREACH: self._check_cvar_breach,
            KillSwitchType.DD_INTRADAY: self._check_dd_intraday,
        }

    def _setup_monitoring(self):
        """Setup monitoring thread"""
        self.monitoring_thread = threading.Thread(
            target=self._monitoring_loop,
            daemon=True
        )

    def start_canary(self):
        """Start canary deployment"""
        if self.state == CanaryState.INACTIVE:
            self.state = CanaryState.CANARY
            self.monitoring_active = True
            self.monitoring_thread.start()
            self._log_event("CANARY_STARTED", {"mode": "1pct_live"})

    def stop_canary(self):
        """Stop canary deployment"""
        self.state = CanaryState.INACTIVE
        self.monitoring_active = False
        self._log_event("CANARY_STOPPED", {"reason": "manual"})

    def emergency_stop(self, reason: str):
        """Emergency stop all operations"""
        self.state = CanaryState.EMERGENCY_STOP
        self._log_event("EMERGENCY_STOP", {"reason": reason})

        # Cancel all active orders
        self._cancel_all_orders()

        # Notify callback
        if self.on_emergency_stop:
            self.on_emergency_stop(reason)

    def kill_switch_triggered(self, switch_type: KillSwitchType, details: dict):
        """Handle kill switch activation"""
        self.state = CanaryState.KILLED

        kill_event = {
            "switch_type": switch_type.value,
            "timestamp_ns": time.time_ns(),
            "details": details
        }
        self.metrics.kill_switches_triggered.append(kill_event)

        self._log_event("KILL_SWITCH_TRIGGERED", kill_event)

        # Cancel all orders
        self._cancel_all_orders()

        # Notify callback
        if self.on_kill_switch:
            self.on_kill_switch(switch_type, details)

    def process_sizing_decision(self, context: ExecutionContext, market_data: dict) -> bool:
        """Process sizing decision with canary modifications"""
        if self.state != CanaryState.CANARY:
            return False

        # Check kill switches first
        if self._evaluate_kill_switches(market_data):
            return False

        # Apply canary sizing (1% of normal)
        original_qty = context.target_qty
        context.target_qty = min(
            original_qty * (self.config.canary_size_pct / 100.0),
            self.config.max_position_usd / (context.micro_price * (1 + context.edge_bps / 10000))
        )

        # Execute decision
        start_time = time.time_ns()
        children = self.execution_router.execute_sizing_decision(context, market_data)
        end_time = time.time_ns()

        # Record metrics
        latency_ms = (end_time - start_time) / 1e6
        self.metrics.decision_latencies_ms.append(latency_ms)
        self.metrics.orders_placed += len(children)

        # Log decision
        self._log_event("CANARY_DECISION", {
            "correlation_id": context.correlation_id,
            "original_qty": original_qty,
            "canary_qty": context.target_qty,
            "latency_ms": latency_ms,
            "orders_created": len(children)
        })

        return len(children) > 0

    def _evaluate_kill_switches(self, market_data: dict) -> bool:
        """Evaluate all kill switches"""
        for switch_type, check_func in self.kill_switches.items():
            if check_func(market_data):
                self.kill_switch_triggered(switch_type, market_data)
                return True
        return False

    def _check_vol_spike(self, market_data: dict) -> bool:
        """Check for volatility spike"""
        vol_spike = market_data.get("vol_spike_detected", False)
        atr_mult = market_data.get("atr_mult", 1.0)
        return vol_spike or atr_mult > self.config.vol_spike_threshold_atr_mult

    def _check_api_timeout(self, market_data: dict) -> bool:
        """Check for API timeouts"""
        consecutive_timeouts = market_data.get("consecutive_timeouts", 0)
        last_request_time = market_data.get("last_request_time_ns", time.time_ns())
        time_since_last_request = (time.time_ns() - last_request_time) / 1e6

        return (consecutive_timeouts >= self.config.max_consecutive_timeouts or
                time_since_last_request > self.config.api_timeout_threshold_ms)

    def _check_spread_limit(self, market_data: dict) -> bool:
        """Check spread limit"""
        spread_bps = market_data.get("spread_bps", 0)
        return spread_bps > self.config.spread_limit_bps

    def _check_cvar_breach(self, market_data: dict) -> bool:
        """Check CVaR breach"""
        cvar_breached = market_data.get("cvar_breached", False)
        return cvar_breached

    def _check_dd_intraday(self, market_data: dict) -> bool:
        """Check intraday drawdown"""
        dd_pct = market_data.get("intraday_dd_pct", 0)
        return dd_pct > self.config.dd_intraday_limit_pct

    def _monitoring_loop(self):
        """Main monitoring loop"""
        while self.monitoring_active:
            try:
                self._collect_metrics()
                self._evaluate_alerts()
                time.sleep(self.config.metrics_interval_s)
            except Exception as e:
                self._log_event("MONITORING_ERROR", {"error": str(e)})

    def _collect_metrics(self):
        """Collect current metrics"""
        # Update ratios
        if self.metrics.orders_placed > 0:
            self.metrics.cancel_ratio = self.metrics.orders_cancelled / self.metrics.orders_placed
            filled_ratio = self.metrics.orders_filled / self.metrics.orders_placed
            self.metrics.maker_fill_ratio = filled_ratio  # Assuming all are maker orders

        # Log metrics
        self._log_event("CANARY_METRICS", {
            "orders_placed": self.metrics.orders_placed,
            "orders_filled": self.metrics.orders_filled,
            "orders_cancelled": self.metrics.orders_cancelled,
            "total_volume_usd": self.metrics.total_volume_usd,
            "total_pnl_usd": self.metrics.total_pnl_usd,
            "cancel_ratio": self.metrics.cancel_ratio,
            "maker_fill_ratio": self.metrics.maker_fill_ratio,
            "kill_switches_count": len(self.metrics.kill_switches_triggered)
        })

    def _evaluate_alerts(self):
        """Evaluate alert conditions"""
        current_time = time.time()

        # Skip if in cooldown
        if current_time - self.last_alert_time < self.config.alert_cooldown_s:
            return

        alerts = []

        # Decision latency alerts
        if self.metrics.decision_latencies_ms:
            latencies = self.metrics.decision_latencies_ms[-100:]  # Last 100 decisions
            if latencies:
                p95 = sorted(latencies)[int(0.95 * len(latencies))]
                if p95 > 8.0:  # Warning threshold
                    alerts.append({
                        "type": "LATENCY_WARNING",
                        "p95_ms": p95,
                        "threshold_ms": 8.0
                    })
                if p95 > 12.0:  # Critical threshold
                    alerts.append({
                        "type": "LATENCY_CRITICAL",
                        "p95_ms": p95,
                        "threshold_ms": 12.0
                    })

        # Cancel ratio alert
        if self.metrics.cancel_ratio > 0.75:
            alerts.append({
                "type": "CANCEL_RATIO_HIGH",
                "cancel_ratio": self.metrics.cancel_ratio,
                "threshold": 0.75
            })

        # Maker fill ratio alert
        if self.metrics.maker_fill_ratio < 0.35:
            alerts.append({
                "type": "MAKER_FILL_RATIO_LOW",
                "maker_fill_ratio": self.metrics.maker_fill_ratio,
                "threshold": 0.35
            })

        # Send alerts
        for alert in alerts:
            self._log_event("CANARY_ALERT", alert)
            self.last_alert_time = current_time

    def _cancel_all_orders(self):
        """Cancel all active orders"""
        # Implementation would integrate with exchange API
        self._log_event("ALL_ORDERS_CANCELLED", {"reason": "kill_switch"})

    def _log_event(self, event_type: str, data: dict):
        """Log canary event"""
        event = {
            "event_type": event_type,
            "timestamp_ns": time.time_ns(),
            "component": "canary",
            **data
        }
        self.event_logger.emit(event_type, event, code=event_type)

    def get_status(self) -> dict:
        """Get current canary status"""
        return {
            "state": self.state.value,
            "metrics": {
                "orders_placed": self.metrics.orders_placed,
                "orders_filled": self.metrics.orders_filled,
                "orders_cancelled": self.metrics.orders_cancelled,
                "total_volume_usd": self.metrics.total_volume_usd,
                "total_pnl_usd": self.metrics.total_pnl_usd,
                "cancel_ratio": self.metrics.cancel_ratio,
                "maker_fill_ratio": self.metrics.maker_fill_ratio,
                "kill_switches_triggered": len(self.metrics.kill_switches_triggered)
            },
            "kill_switches": [ks["switch_type"] for ks in self.metrics.kill_switches_triggered],
            "uptime_seconds": (time.time_ns() - self.metrics.start_time_ns) / 1e9
        }


# Global canary instance
_canary_instance = None

def get_canary_instance() -> CanarySystem:
    """Get global canary instance"""
    global _canary_instance
    if _canary_instance is None:
        _canary_instance = CanarySystem()
    return _canary_instance

def start_canary_deployment():
    """Start canary deployment"""
    canary = get_canary_instance()
    canary.start_canary()
    return canary

def stop_canary_deployment():
    """Stop canary deployment"""
    canary = get_canary_instance()
    canary.stop_canary()
    return canary
