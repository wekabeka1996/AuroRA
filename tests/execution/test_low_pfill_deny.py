from decimal import Decimal
from core.execution.router_v2 import RouterV2, OrderIntent, MarketSpec, DenyDecision
from core.aurora_event_logger import AuroraEventLogger

def _intent(post_only=True, edge=6, qty=Decimal('1')):
    return OrderIntent(intent_id='i2', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=edge, stop_dist_bps=50,
                       tp_targets_bps=[100], risk_ctx={'equity_usd':'10000'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={'post_only':post_only}, qty_hint=qty)

def _market():
    mid=Decimal('100')
    best_bid=Decimal('99.97')
    best_ask=Decimal('100.03')
    spread_bps=float((best_ask-best_bid)/((best_ask+best_bid)/2)*10000)
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=best_bid, best_ask=best_ask, spread_bps=spread_bps, mid=mid)

def _router():
    cfg={'execution':{'router':{'pfill_min':0.65,'capture_eta':0.5,'rebate_mode':True,'maker_spread_ok_bps':10,'spread_deny_bps':50,'switch_margin_bps':0.1},'sla':{'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0}}}
    return RouterV2(config=cfg, event_logger=AuroraEventLogger())


def test_low_pfill_deny_post_only():
    r=_router()
    intent=_intent(post_only=True)
    m=_market()
    # Set low p_fill via small T and moderate negative OBI, and deep queue
    features={'obi':-0.3,'pred_latency_ms':5.0,'queue_pos':5.0,'depth_at_price':5.0}
    dec=r.route(intent,m,latency_ms=5.0,features=features)
    assert isinstance(dec, DenyDecision)
    assert dec.code.startswith('LOW_PFILL')


def test_low_pfill_taker_fallback():
    r=_router()
    # Increase expected edge to make taker EV positive
    intent=_intent(post_only=False, edge=12)
    m=_market()
    features={'obi':-0.3,'pred_latency_ms':5.0,'queue_pos':5.0,'depth_at_price':5.0}
    dec=r.route(intent,m,latency_ms=5.0,features=features)
    # Should allow via taker if taker EV positive
    assert not isinstance(dec, DenyDecision)
    assert dec.mode=='taker'
