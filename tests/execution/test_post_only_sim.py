from decimal import Decimal
from core.execution.router_v2 import DenyDecision, RouterV2
import pytest


def test_buy_post_only_never_crosses_spread(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(side='BUY', expected_return_bps=40, post_only=True)
    mspec = market_spec_factory(tick_size='0.10', best_bid='30000', best_ask='30000.6')
    monkeypatch.setattr(RouterV2, '_p_fill', lambda self, f, s: Decimal('0.8'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=20)
    if not isinstance(res, DenyDecision) and res.mode == 'maker' and res.price:
        assert Decimal(str(res.price)) <= Decimal('30000'), 'BUY maker must not cross spread'


def test_sell_post_only_never_crosses_spread(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(side='SELL', expected_return_bps=40, post_only=True)
    mspec = market_spec_factory(tick_size='0.10', best_bid='30000', best_ask='30000.6')
    monkeypatch.setattr(RouterV2, '_p_fill', lambda self, f, s: Decimal('0.8'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=20)
    if not isinstance(res, DenyDecision) and res.mode == 'maker' and res.price:
        assert Decimal(str(res.price)) >= Decimal('30000.6'), 'SELL maker must not cross spread'
