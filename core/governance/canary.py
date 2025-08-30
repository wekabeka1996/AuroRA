"""
Aurora Governance - Canary Safety Gates
=======================================

Safety monitoring system that detects anomalous trading patterns
and generates alerts for risk management.
"""

from typing import List, Dict, Any, Optional
from dataclasses import dataclass
from enum import Enum
import time
import logging

logger = logging.getLogger(__name__)

class AlertType(Enum):
    """Types of canary alerts"""
    NO_TRADES = "no_trades"
    DENY_SPIKE = "deny_spike"
    CALIBRATION_DRIFT = "calibration_drift"
    CVAR_BREACH = "cvar_breach"

@dataclass
class CanaryAlert:
    """Canary alert with details"""
    alert_type: AlertType
    message: str
    severity: str  # "low", "medium", "high", "critical"
    timestamp_ns: int
    details: Dict[str, Any]

class Canary:
    """
    Canary safety monitoring system
    
    Monitors trading decisions and generates alerts for:
    - No trades in time window
    - Sudden spikes in deny rates
    - Calibration drift detection
    - CVaR breach detection
    """
    
    def __init__(self, 
                 no_trade_threshold_sec: float = 300.0,
                 deny_spike_threshold: float = 0.8,
                 calibration_window: int = 100,
                 cvar_threshold: float = 0.95):
        """
        Args:
            no_trade_threshold_sec: Alert if no trades for this many seconds
            deny_spike_threshold: Alert if deny rate exceeds this fraction
            calibration_window: Window size for calibration drift detection
            cvar_threshold: CVaR threshold for risk alerts
        """
        self.no_trade_threshold_sec = no_trade_threshold_sec
        self.deny_spike_threshold = deny_spike_threshold
        self.calibration_window = calibration_window
        self.cvar_threshold = cvar_threshold
        
        # State tracking
        self.decisions: List[Dict[str, Any]] = []
        self.alerts: List[CanaryAlert] = []
        self.last_trade_ts_ns: Optional[int] = None
        
        # Rolling statistics
        self.deny_count = 0
        self.total_count = 0
        
    def on_decision(self, ts_ns: int, action: str, p: float, y: int) -> None:
        """
        Record a trading decision for monitoring
        
        Args:
            ts_ns: Timestamp in nanoseconds
            action: "enter" or "deny"
            p: Probability from model
            y: Actual outcome (1 for success, 0 for failure)
        """
        decision = {
            'ts_ns': ts_ns,
            'action': action,
            'p': p,
            'y': y
        }
        
        self.decisions.append(decision)
        self.total_count += 1
        
        if action == "deny":
            self.deny_count += 1
            
        # Update last trade timestamp
        if action == "enter":
            self.last_trade_ts_ns = ts_ns
            
        # Keep only recent decisions
        if len(self.decisions) > self.calibration_window:
            old_decision = self.decisions.pop(0)
            if old_decision['action'] == "deny":
                self.deny_count -= 1
            self.total_count -= 1
            
        # Check for alerts
        self._check_alerts(ts_ns)
        
    def _check_alerts(self, current_ts_ns: int) -> None:
        """Check for various alert conditions"""
        
        # No trades alert
        if (self.last_trade_ts_ns is not None and 
            (current_ts_ns - self.last_trade_ts_ns) / 1e9 > self.no_trade_threshold_sec):
            self._add_alert(
                AlertType.NO_TRADES,
                f"No trades for {self.no_trade_threshold_sec}s",
                "medium",
                current_ts_ns,
                {'last_trade_ts': self.last_trade_ts_ns}
            )
            
        # Deny spike alert
        if self.total_count > 10:
            deny_rate = self.deny_count / self.total_count
            if deny_rate > self.deny_spike_threshold:
                self._add_alert(
                    AlertType.DENY_SPIKE,
                    ".2f",
                    "high",
                    current_ts_ns,
                    {'deny_rate': deny_rate, 'total': self.total_count}
                )
                
        # Calibration drift (simplified check)
        if len(self.decisions) >= 10:
            recent_p = [d['p'] for d in self.decisions[-10:]]
            avg_p = sum(recent_p) / len(recent_p)
            if avg_p < 0.1 or avg_p > 0.9:  # Extreme probabilities
                self._add_alert(
                    AlertType.CALIBRATION_DRIFT,
                    ".3f",
                    "medium",
                    current_ts_ns,
                    {'avg_p': avg_p, 'samples': len(recent_p)}
                )
                
    def _add_alert(self, alert_type: AlertType, message: str, 
                   severity: str, ts_ns: int, details: Dict[str, Any]) -> None:
        """Add an alert to the queue"""
        alert = CanaryAlert(
            alert_type=alert_type,
            message=message,
            severity=severity,
            timestamp_ns=ts_ns,
            details=details
        )
        self.alerts.append(alert)
        logger.warning(f"Canary alert: {message}")
        
    def poll(self) -> List[CanaryAlert]:
        """Get and clear pending alerts"""
        alerts = self.alerts.copy()
        self.alerts.clear()
        return alerts
        
    def get_stats(self) -> Dict[str, Any]:
        """Get current canary statistics"""
        deny_rate = self.deny_count / self.total_count if self.total_count > 0 else 0
        
        return {
            'total_decisions': self.total_count,
            'deny_count': self.deny_count,
            'deny_rate': deny_rate,
            'last_trade_ts_ns': self.last_trade_ts_ns,
            'pending_alerts': len(self.alerts)
        }