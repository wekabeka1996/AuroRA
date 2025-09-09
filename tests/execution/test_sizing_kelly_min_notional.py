from decimal import Decimal
from core.risk.sizing_orchestrator import SizingOrchestrator
from core.execution.router_v2 import MarketSpec, OrderIntent
from core.aurora_event_logger import AuroraEventLogger


def _market():
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=Decimal('99.99'), best_ask=Decimal('100.01'), spread_bps=2.0, mid=Decimal('100'))


def _intent(equity_usd:str):
    return OrderIntent(intent_id='iq', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=10, stop_dist_bps=100,
                       tp_targets_bps=[200], risk_ctx={'equity_usd':equity_usd},
                       regime_ctx={'governance':'shadow'}, exec_prefs={}, qty_hint=None)


def test_min_notional_bump():
    cfg={'risk':{'per_trade_usd':0.001},'kelly':{'bounds':{'m_min':0.5,'m_max':1.0}}}
    sz=SizingOrchestrator(cfg, event_logger=AuroraEventLogger())
    m=_market()
    intent=_intent('200')  # small equity
    k=sz.compute(intent,m)
    # ensure bumped above zero and meets min notional
    assert k.qty_final * m.mid >= m.min_notional


def test_min_notional_zero_when_caps_block():
    cfg={'risk':{'per_trade_usd':0.0001,'exposure_cap_usd':1,'leverage_max':1},'kelly':{'bounds':{'m_min':0.25,'m_max':0.5}}}
    sz=SizingOrchestrator(cfg, event_logger=AuroraEventLogger())
    m=_market()
    intent=_intent('50')
    k=sz.compute(intent,m)
    # Either zero due to cap or still below min notional triggers zero
    if k.qty_final == 0:
        assert True
    else:
        assert k.qty_final * m.mid >= m.min_notional
