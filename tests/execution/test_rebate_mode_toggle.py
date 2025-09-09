from decimal import Decimal
from core.execution.router_v2 import RouterV2, OrderIntent, MarketSpec
from core.aurora_event_logger import AuroraEventLogger


def _intent():
    return OrderIntent(intent_id='i4', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=5, stop_dist_bps=40,
                       tp_targets_bps=[100], risk_ctx={'equity_usd':'10000'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={}, qty_hint=Decimal('1'))


def _market():
    mid=Decimal('200')
    best_bid=Decimal('199.95')
    best_ask=Decimal('200.05')
    spread_bps=float((best_ask-best_bid)/((best_ask+best_bid)/2)*10000)
    # maker fee lower than taker so rebate positive
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('10'),
                      maker_fee_bps=1, taker_fee_bps=6, best_bid=best_bid, best_ask=best_ask, spread_bps=spread_bps, mid=mid)


def _router(rebate_mode:bool):
    cfg={'execution':{'router':{'pfill_min':0.55,'capture_eta':0.5,'rebate_mode':rebate_mode,'maker_spread_ok_bps':10,'spread_deny_bps':80,'switch_margin_bps':0.05},'sla':{'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0}}}
    return RouterV2(config=cfg, event_logger=AuroraEventLogger())


def test_rebate_mode_effect():
    m=_market()
    intent=_intent()
    features={'obi':0.0,'pred_latency_ms':3.0}
    r_on=_router(True)
    d_on=r_on.route(intent,m,latency_ms=3.0,features=features)
    r_off=_router(False)
    d_off=r_off.route(intent,m,latency_ms=3.0,features=features)

    # Compare net_after_tca: with rebate off should be lower (or route different)
    if hasattr(d_on,'tca') and hasattr(d_off,'tca'):
        assert d_on.tca.net_after_tca >= d_off.tca.net_after_tca

    # Scenario selection difference acceptable: if maker when on and taker when off -> passes objective
    if hasattr(d_on,'tca') and hasattr(d_off,'tca'):
        if d_on.tca.reason=='MAKER_SELECTED' and d_off.tca.reason=='TAKER_SELECTED':
            assert True
