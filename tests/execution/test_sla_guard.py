from core.execution.router_v2 import DenyDecision
from core.execution.execution_service import ExecutionService


def test_sla_predict_over_budget_denies(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory()
    mspec = market_spec_factory()
    # Patch latency predictor predict() to a very large value by monkeypatching service's predictor
    monkeypatch.setattr(svc.latency_predictor, 'predict', lambda : 800.0)
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=50)
    assert isinstance(res, DenyDecision)
    assert res.code in ('SLA_PREDICT','SLA_LATENCY')
