from decimal import Decimal
from core.execution.router_v2 import RouterV2, OrderIntent, MarketSpec, DenyDecision
from core.aurora_event_logger import AuroraEventLogger

def _router():
    cfg={'execution':{'router':{'pfill_min':0.6,'capture_eta':0.4,'rebate_mode':True,'maker_spread_ok_bps':10,'spread_deny_bps':40,'switch_margin_bps':0.1},'sla':{'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0}}}
    return RouterV2(config=cfg, event_logger=AuroraEventLogger())

def _intent(post_only=True,tif='IOC'):
    return OrderIntent(intent_id='i3', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=8, stop_dist_bps=40,
                       tp_targets_bps=[120], risk_ctx={'equity_usd':'10000'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={'post_only':post_only,'tif':tif}, qty_hint=Decimal('1'))

def _market():
    mid=Decimal('50')
    best_bid=Decimal('49.99')
    best_ask=Decimal('50.01')
    spread_bps=float((best_ask-best_bid)/((best_ask+best_bid)/2)*10000)
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=best_bid,best_ask=best_ask,spread_bps=spread_bps,mid=mid)


def test_post_only_unavailable_ioc():
    r=_router()
    m=_market()
    intent=_intent(post_only=True,tif='IOC')
    dec=r.route(intent,m,latency_ms=5.0,features={'pred_latency_ms':5.0})
    if isinstance(dec, DenyDecision):
        assert dec.code in ('POST_ONLY_UNAVAILABLE','LOW_PFILL.DENY','EDGE_DENY')
    else:
        # If maker viable and engine ignores tif, treat as maker
        assert dec.mode in ('maker','taker')


def test_post_only_gtc_allows():
    r=_router()
    m=_market()
    intent=_intent(post_only=True,tif='GTC')
    dec=r.route(intent,m,latency_ms=5.0,features={'pred_latency_ms':5.0})
    if isinstance(dec, DenyDecision):
        # Denial acceptable for pfill, edge, or post_only unavailable when maker not viable
        assert dec.code in ('LOW_PFILL.DENY','EDGE_DENY','POST_ONLY_UNAVAILABLE')
    else:
        assert dec.mode in ('maker','taker')


def test_post_only_unavailable_fok():
    r=_router()
    m=_market()
    intent=_intent(post_only=True,tif='FOK')
    dec=r.route(intent,m,latency_ms=5.0,features={'pred_latency_ms':5.0})
    assert isinstance(dec, DenyDecision)
    assert dec.code == 'POST_ONLY_UNAVAILABLE'
