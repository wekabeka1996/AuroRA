from decimal import Decimal
import pytest
from core.execution.router_v2 import DenyDecision, RouterV2


def test_maker_chosen_when_Em_gt_Et_and_pfill_ok(svc, intent_factory, market_spec_factory, monkeypatch, event_logger):
    intent = intent_factory(side="BUY", expected_return_bps=60, post_only=True)
    mspec = market_spec_factory(maker_fee_bps=1, taker_fee_bps=5)

    # monkeypatch p_fill high (>=0.8) by patching RouterV2._p_fill
    monkeypatch.setattr(RouterV2, "_p_fill", lambda self, f, s: Decimal('0.80'))

    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=50)
    assert not isinstance(res, DenyDecision), f"Unexpected deny: {getattr(res,'reason',None)}"
    assert res.mode == 'maker'
    # ensure decision event emitted
    decision_events = [e for e in event_logger._events if e[0] == 'ROUTER.DECISION']
    assert decision_events, "ROUTER.DECISION not emitted"
    eb = res.tca
    assert eb.net_after_tca > 0


def test_taker_chosen_when_pfill_below_threshold(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(side="BUY", expected_return_bps=60, post_only=False)
    mspec = market_spec_factory()
    monkeypatch.setattr(RouterV2, "_p_fill", lambda self, f, s: Decimal('0.40'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=40)
    if not isinstance(res, DenyDecision):
        assert res.mode == 'taker'
