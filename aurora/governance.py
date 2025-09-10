from __future__ import annotations

import time
from typing import Any

from observability.codes import AURORA_HALT, DQ_EVENT_ABNORMAL_SPREAD, DQ_EVENT_CROSSED_BOOK, DQ_EVENT_STALE_BOOK


class Governance:
    def __init__(self, cfg: dict[str, Any] | None = None):
        self.cfg = cfg or {}
        self._halt_until_ts: float = 0.0

    def _is_halted(self) -> bool:
        return time.time() < self._halt_until_ts

    def _maybe_halt(self, reject_rate: float, is_critical_dq: bool) -> None:
        gates = (self.cfg.get('gates') or {})
        storm = float(gates.get('reject_storm_pct', 0.5))
        cooldown = int(gates.get('reject_storm_cooldown_s', 60))
        if is_critical_dq or reject_rate >= storm:
            self._halt_until_ts = max(self._halt_until_ts, time.time() + cooldown)

    def resume(self) -> None:
        self._halt_until_ts = 0.0

    def approve(self, intent: dict[str, Any], risk_state: dict[str, Any]) -> dict[str, Any]:
        """Return approved intent or deny with code. Implements spread/latency/volatility guards,
        daily drawdown and CVaR checks, and a kill-switch based on reject storms or DQ critical signals.
        """
        reasons: list[str] = []
        gates = (self.cfg.get('gates') or {})
        # kill-switch check first
        stats = (risk_state.get('recent_stats') or {})
        total = int(stats.get('total') or 0)
        rejects = int(stats.get('rejects') or 0)
        reject_rate = (rejects / total) if total > 0 else 0.0
        dq_flags = risk_state.get('dq', {}) or {}
        is_critical_dq = bool(dq_flags.get('stale_book') or dq_flags.get('crossed_book'))
        self._maybe_halt(reject_rate, is_critical_dq)
        if self._is_halted():
            return {"allow": False, "code": AURORA_HALT, "reasons": ["killswitch_active"], "intent": intent}

        # Data-quality gates
        if dq_flags.get('stale_book'):
            return {"allow": False, "code": DQ_EVENT_STALE_BOOK, "reasons": ["stale_book"], "intent": intent}
        if dq_flags.get('crossed_book'):
            return {"allow": False, "code": DQ_EVENT_CROSSED_BOOK, "reasons": ["crossed_book"], "intent": intent}
        if dq_flags.get('abnormal_spread'):
            return {"allow": False, "code": DQ_EVENT_ABNORMAL_SPREAD, "reasons": ["abnormal_spread"], "intent": intent}

        # Risk limits: daily DD and CVaR
        dd_lim = float(gates.get('daily_dd_limit_pct', 10.0))
        cvar_alpha = float(gates.get('cvar_alpha', 0.1))  # unused placeholder
        cvar_limit = float(gates.get('cvar_limit', 0.0))
        pnl_today_pct = float(risk_state.get('pnl_today_pct') or 0.0)
        if pnl_today_pct < -abs(dd_lim):
            return {"allow": False, "code": "RISK.DENY.DRAWDOWN", "reasons": ["daily_dd"], "intent": intent}
        cvar_hist = risk_state.get('cvar_hist')  # expected negative values
        if cvar_hist is not None and float(cvar_hist) < -abs(cvar_limit):
            return {"allow": False, "code": "RISK.DENY.CVAR", "reasons": ["cvar_limit"], "intent": intent}

        # Market microstructure guards
        spread_bps = float(risk_state.get('spread_bps') or 0.0)
        if spread_bps > float(gates.get('spread_bps_limit', 80)):
            return {"allow": False, "code": "SPREAD_GUARD_TRIP", "reasons": ["spread_limit"], "intent": intent}
        latency_ms = float(risk_state.get('latency_ms') or 0.0)
        if latency_ms > float(gates.get('latency_ms_limit', 500)):
            return {"allow": False, "code": "LATENCY_GUARD_TRIP", "reasons": ["latency_limit"], "intent": intent}
        vol_std_bps = float(risk_state.get('vol_std_bps') or 0.0)
        if vol_std_bps > float(gates.get('vol_guard_std_bps', 300)):
            return {"allow": False, "code": "VOLATILITY_GUARD_TRIP", "reasons": ["volatility_limit"], "intent": intent}

        # Position limits
        pos_now = int(risk_state.get('open_positions') or 0)
        pos_limit = int(gates.get('max_concurrent_positions', 999))
        if pos_now >= pos_limit:
            return {"allow": False, "code": "RISK.DENY.POS_LIMIT", "reasons": ["pos_limit"], "intent": intent}

        return {"allow": True, "intent": intent, "reasons": reasons}
