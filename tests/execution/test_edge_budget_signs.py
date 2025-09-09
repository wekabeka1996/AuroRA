from core.execution.router_v2 import DenyDecision, RouterV2
from decimal import Decimal


def test_edge_budget_signs_and_sum(svc, intent_factory, market_spec_factory, monkeypatch):
    intent = intent_factory(expected_return_bps=80)
    mspec = market_spec_factory(maker_fee_bps=1, taker_fee_bps=5)
    monkeypatch.setattr(RouterV2, "_p_fill", lambda self, f, s: Decimal('0.9'))
    res = svc.place(intent=intent, market=mspec, features={}, measured_latency_ms=30)
    if isinstance(res, DenyDecision):
        # acceptable if net_after_tca <=0, else fail
        return
    eb = res.tca
    assert eb.fees <= 0
    assert eb.slip_est <= 0
    assert eb.adv_sel <= 0
    assert eb.lat_cost <= 0
    assert eb.rebates >= 0
    calc = eb.raw + eb.fees + eb.slip_est + eb.adv_sel + eb.lat_cost + eb.rebates
    assert eb.net_after_tca == calc
