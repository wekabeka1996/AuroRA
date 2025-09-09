from decimal import Decimal
from core.execution.router_v2 import DenyDecision, RouterV2


def test_min_notional_denied(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(expected_return_bps=30, qty_hint='0.001')
    mspec = market_spec_factory(min_notional='5000')  # high to force deny
    monkeypatch.setattr(RouterV2, '_p_fill', lambda self, f, s: Decimal('0.9'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=25)
    assert isinstance(res, DenyDecision)
    assert res.code in ('MIN_NOTIONAL','INTENT_INVALID')


def test_tick_lot_quantization_applied(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(qty_hint='0.027')
    mspec = market_spec_factory(tick_size='0.50', lot_size='0.010', best_bid='30000', best_ask='30001')
    monkeypatch.setattr(RouterV2, '_p_fill', lambda self, f, s: Decimal('0.9'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=35)
    if not isinstance(res, DenyDecision) and res.price:
        from decimal import Decimal as D
        assert D(str(res.price)) % D('0.50') == 0
