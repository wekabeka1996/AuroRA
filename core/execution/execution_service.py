"""ExecutionService facade skeleton.

Implements place(intent) -> RoutedOrderPlan | DenyDecision using:
 - LatencyPredictor (predict phase)
 - SLAMonitor (actual phase)
 - Sizing orchestrator (stub)
 - RouterV2 (skeleton)
 - AuroraEventLogger for XAI events
"""
from __future__ import annotations
from typing import Dict, Any, Union
from decimal import Decimal
from core.aurora_event_logger import AuroraEventLogger
from .router_v2 import OrderIntent, RoutedOrderPlan, DenyDecision, RouterV2, MarketSpec, EdgeBudget, KellyApplied
from .latency_predictor import LatencyPredictor
from core.execution.sla import SLAMonitor  # existing SLA monitor
from core.risk.sizing_orchestrator import SizingOrchestrator

class ExecutionService:
    def __init__(self, *, config: Dict[str, Any], event_logger: AuroraEventLogger | None = None):
        self.cfg = config or {}
        self.logger = event_logger or AuroraEventLogger()
        self.router = RouterV2(config=self.cfg, event_logger=self.logger)
        sla_cfg = self.cfg.get('execution', {}).get('sla', {})
        self.sla_monitor = SLAMonitor(
            kappa_bps_per_ms=float(sla_cfg.get('kappa_bps_per_ms', 0.01)),
            edge_floor_bps=float(sla_cfg.get('edge_floor_bps', 0.0)),
            max_latency_ms=float(sla_cfg.get('max_latency_ms', 250.0))
        )
        self.latency_predictor = LatencyPredictor()
        # sizing orchestrator (pass same event logger for CVaR shift events)
        self.sizing = SizingOrchestrator(self.cfg, event_logger=self.logger)

    # ---- public API ----
    def place(self, intent: OrderIntent, market: MarketSpec, features: Dict[str, Any], *, measured_latency_ms: float) -> Union[RoutedOrderPlan, DenyDecision]:
        # 1. log intent
        self.logger.emit('ORDER.INTENT.RECEIVED', { 'intent_id': intent.intent_id, 'symbol': intent.symbol, 'side': intent.side, 'expected_return_bps': intent.expected_return_bps })

        # 2. SLA predict phase (using measured as proxy until pre-measure available)
        self.latency_predictor.update(measured_latency_ms)
        pred = self.latency_predictor.predict()
        # ensure Decimal arithmetic
        edge = Decimal(str(intent.expected_return_bps))
        kappa = self.router.kappa_bps_per_ms  # Decimal
        pred_dec = Decimal(str(pred))
        edge_after_pred = edge - kappa * pred_dec
        if pred_dec > self.router.max_latency_ms or edge_after_pred <= self.router.edge_floor_bps:
            self.logger.emit('SLA.DENY', { 'phase': 'predict', 'latency_ms': pred, 'edge_after_pred': edge_after_pred, 'intent_id': intent.intent_id })
            return DenyDecision(code='SLA_PREDICT', stage='sla_predict', reason='Predicted latency or edge floor breach', diagnostics={'pred_latency_ms': pred, 'edge_after_pred': edge_after_pred}, validations=[])
        self.logger.emit('SLA.CHECK', { 'phase': 'predict', 'latency_ms': pred, 'edge_after_pred': edge_after_pred, 'intent_id': intent.intent_id })

        # 3. Sizing (Kelly)
        kelly = self.sizing.compute(intent, market)
        # 3.1 Deny on zero size
        if kelly.qty_final <= Decimal('0'):
            self.logger.emit('ORDER.DENY', { 'intent_id': intent.intent_id, 'code': 'SIZE_ZERO.DENY', 'stage': 'sizing' })
            return DenyDecision(code='SIZE_ZERO.DENY', stage='sizing', reason='final sized qty is zero', diagnostics={'qty_final': str(kelly.qty_final)}, validations=[])
        # 4. Route
        features = dict(features or {})
        features.setdefault('pred_latency_ms', float(pred))
        # propagate qty hint for router economic viability checks
        intent.qty_hint = kelly.qty_final
        decision = self.router.route(intent, market, measured_latency_ms, features)
        if isinstance(decision, DenyDecision):
            self.logger.emit('ORDER.DENY', { 'intent_id': intent.intent_id, 'code': decision.code, 'stage': decision.stage })
            return decision

        # 4. Actual SLA check
        sla_res = self.sla_monitor.check(edge_bps=float(edge), latency_ms=measured_latency_ms)
        if not sla_res.allow:
            self.logger.emit('SLA.DENY', { 'phase': 'actual', 'latency_ms': measured_latency_ms, 'edge_after_bps': sla_res.edge_after_bps, 'intent_id': intent.intent_id })
            return DenyDecision(code='SLA_ACTUAL', stage='sla_actual', reason=sla_res.reason, diagnostics={'latency_ms': measured_latency_ms, 'edge_after_bps': sla_res.edge_after_bps}, validations=[])
        self.logger.emit('SLA.CHECK', { 'phase': 'actual', 'latency_ms': measured_latency_ms, 'edge_after_bps': sla_res.edge_after_bps, 'intent_id': intent.intent_id })

        # 5. Enrich plan with sizing
        if isinstance(decision, RoutedOrderPlan):
            decision.qty = str(kelly.qty_final)
            decision.sizing = kelly
            self.logger.emit('ORDER.PLAN.BUILD', { 'intent_id': intent.intent_id, 'mode': decision.mode, 'qty': decision.qty, 'price': decision.price })
        return decision

__all__ = ['ExecutionService']
