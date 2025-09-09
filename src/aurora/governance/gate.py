from __future__ import annotations
from typing import Dict, Any
from core.aurora_event_logger import AuroraEventLogger
from tools.metrics_exporter import METRICS
from .models import PerfSnapshot, GovernanceDecision
from .alpha_ledger import AlphaLedger


class GovernanceGate:
    def __init__(self, config: Dict[str, Any], event_logger: AuroraEventLogger | None = None, alpha_ledger: AlphaLedger | None = None):
        self.cfg = config or {}
        self.logger = event_logger or AuroraEventLogger()
        gov = (self.cfg.get('governance') or {})
        self.soak = gov.get('soak', {})
        self.thr = gov.get('thresholds', {})
        a = gov.get('alpha', {})
        self.spend_canary_to_live = float(a.get('spend_canary_to_live', 0.02))
        self.spend_shadow_to_canary = float(a.get('spend_shadow_to_canary', 0.01))
        self.alpha_ledger = alpha_ledger or AlphaLedger(budget_total=float(a.get('budget_total', 0.10)), event_logger=self.logger)

    def evaluate(self, perf: PerfSnapshot, state: str, now_ms: int) -> GovernanceDecision:
        # Defaults and thresholds
        sr_min_live = float(self.thr.get('sr_min_live', 2.0))
        p_glr_max_live = float(self.thr.get('p_glr_max_live', 0.05))
        edge_min = float(self.thr.get('edge_mean_bps_min', 0.0))
        sla_p95_ms_max = float(self.thr.get('sla_p95_ms_max', 500))
        sla_breach_rate_max = float(self.thr.get('sla_breach_rate_max', 0.01))
        xai_missing_rate_max = float(self.thr.get('xai_missing_rate_max', 0.01))
        min_trades_canary = int((self.soak or {}).get('min_trades_canary', 300))
        min_minutes_canary = int((self.soak or {}).get('min_minutes_canary', 60))

        # Red flags immediate to shadow
        if perf.cvar_breach or (perf.sla_breach_rate > sla_breach_rate_max) or (perf.xai_missing_rate > xai_missing_rate_max):
            self.logger.emit('GOVERNANCE.EVAL', { 'state': state, 'perf': perf.__dict__, 'proposal': 'shadow', 'reason': 'red_flag' })
            try: METRICS.aurora.inc_route_decision  # ensure metrics
            except Exception: pass
            METRICS.aurora.inc_route_decision('shadow') if hasattr(METRICS,'aurora') else None
            self.logger.emit('GOVERNANCE.TRANSITION', { 'from': state, 'to': 'shadow', 'reason': 'red_flag', 'alpha': 0.0 })
            try:
                METRICS.governance.on_transition(state, 'shadow', 'red_flag')
            except Exception:
                pass
            return GovernanceDecision(mode='shadow', reason='red_flag', alpha_spent=0.0, allow=False)

        # shadow -> canary
        if state == 'shadow':
            ok = (perf.sprt_pass and perf.edge_mean_bps >= edge_min and perf.latency_p95_ms <= sla_p95_ms_max and perf.sla_breach_rate <= sla_breach_rate_max and perf.xai_missing_rate <= xai_missing_rate_max)
            if ok:
                if self.alpha_ledger.can_spend(self.spend_shadow_to_canary):
                    self.alpha_ledger.spend(self.spend_shadow_to_canary, reason='shadow_to_canary', now_ms=now_ms)
                    self.logger.emit('GOVERNANCE.TRANSITION', { 'from': 'shadow', 'to': 'canary', 'reason': 'sprt_ok', 'alpha': self.spend_shadow_to_canary })
                    try:
                        if hasattr(METRICS,'aurora'): METRICS.aurora.inc_route_decision('canary')
                        METRICS.governance.on_transition('shadow', 'canary', 'sprt_ok')
                    except Exception: pass
                    return GovernanceDecision(mode='canary', reason='sprt_ok', alpha_spent=self.spend_shadow_to_canary, allow=True)
                else:
                    self.logger.emit('GOVERNANCE.EVAL', { 'state': state, 'perf': perf.__dict__, 'proposal': 'canary', 'reason': 'alpha_budget_exhausted' })
                    try:
                        METRICS.governance.on_deny('alpha_budget_exhausted')
                    except Exception:
                        pass
                    return GovernanceDecision(mode='shadow', reason='alpha_budget_exhausted', alpha_spent=0.0, allow=False)

        # canary -> live
        if state == 'canary':
            soak_ok = (perf.trades >= min_trades_canary) and (perf.window_ms >= min_minutes_canary * 60_000)
            ok = (perf.sprt_pass and (perf.pvalue_glr <= p_glr_max_live) and (perf.sr >= sr_min_live) and soak_ok and (perf.sla_breach_rate <= sla_breach_rate_max) and (perf.xai_missing_rate <= xai_missing_rate_max))
            if ok:
                if self.alpha_ledger.can_spend(self.spend_canary_to_live):
                    self.alpha_ledger.spend(self.spend_canary_to_live, reason='canary_to_live', now_ms=now_ms)
                    self.logger.emit('GOVERNANCE.TRANSITION', { 'from': 'canary', 'to': 'live', 'reason': 'soak_ok', 'alpha': self.spend_canary_to_live })
                    try:
                        if hasattr(METRICS,'aurora'): METRICS.aurora.inc_route_decision('live')
                        METRICS.governance.on_transition('canary', 'live', 'soak_ok')
                    except Exception: pass
                    return GovernanceDecision(mode='live', reason='soak_ok', alpha_spent=self.spend_canary_to_live, allow=True)
                else:
                    self.logger.emit('GOVERNANCE.EVAL', { 'state': state, 'perf': perf.__dict__, 'proposal': 'live', 'reason': 'alpha_budget_exhausted' })
                    try:
                        METRICS.governance.on_deny('alpha_budget_exhausted')
                    except Exception:
                        pass
                    return GovernanceDecision(mode='canary', reason='alpha_budget_exhausted', alpha_spent=0.0, allow=False)

        # stay
        self.logger.emit('GOVERNANCE.EVAL', { 'state': state, 'perf': perf.__dict__, 'proposal': state, 'reason': 'no_transition' })
        return GovernanceDecision(mode=state, reason='no_transition', alpha_spent=0.0, allow=False)
