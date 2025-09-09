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
    features={'obi':-0.2,'pred_latency_ms':5.0}  # will reduce p_fill
    dec=r.route(intent,m,latency_ms=5.0,features=features)
    assert isinstance(dec, DenyDecision)
    assert dec.code=='POST_ONLY_UNAVAILABLE' or dec.code.startswith('LOW_PFILL')


def test_low_pfill_taker_fallback():
    r=_router()
    intent=_intent(post_only=False)
    m=_market()
    features={'obi':-0.2,'pred_latency_ms':5.0}
    dec=r.route(intent,m,latency_ms=5.0,features=features)
    # Should allow via taker if taker EV positive
    if isinstance(dec, DenyDecision):
        # if p_fill too low and maker positive but not viable we expect LOW_PFILL.DENY
        assert dec.code in ('LOW_PFILL.DENY','EDGE_DENY')
    else:
        assert dec.mode=='taker'
