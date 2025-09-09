from __future__ import annotations
from dataclasses import dataclass
from typing import Optional
from core.aurora_event_logger import AuroraEventLogger


@dataclass
class AlphaState:
    budget_total: float
    spent_total: float
    updated_ms: int


class AlphaLedger:
    def __init__(self, *, budget_total: float, event_logger: Optional[AuroraEventLogger] = None):
        self._state = AlphaState(budget_total=float(budget_total), spent_total=0.0, updated_ms=0)
        self._logger = event_logger or AuroraEventLogger()

    def load(self) -> AlphaState:
        return self._state

    def can_spend(self, delta_alpha: float) -> bool:
        try:
            return (self._state.spent_total + float(delta_alpha)) <= self._state.budget_total + 1e-12
        except Exception:
            return False

    def spend(self, delta_alpha: float, reason: str, now_ms: int) -> AlphaState:
        if not self.can_spend(delta_alpha):
            return self._state
        self._state.spent_total = float(self._state.spent_total) + float(delta_alpha)
        self._state.updated_ms = int(now_ms)
        # XAI event
        self._logger.emit('ALPHA.LEDGER.UPDATE', {
            'delta': float(delta_alpha), 'spent_total': float(self._state.spent_total), 'budget_total': float(self._state.budget_total), 'reason': reason,
            'ts_ms': int(now_ms)
        })
        # Metric gauge
        try:
            from tools.metrics_exporter import METRICS
            METRICS.aurora.set_cvar_current_usd  # ensure module loaded
            remain = max(0.0, float(self._state.budget_total) - float(self._state.spent_total))
            METRICS.governance.alpha_remaining('global', remain)
            METRICS.governance.set_alpha_spent_total(float(self._state.spent_total))
        except Exception:
            pass
        return self._state
