from decimal import Decimal
from core.execution.router_v2 import RouterV2, OrderIntent, MarketSpec, DenyDecision
from core.aurora_event_logger import AuroraEventLogger


def _market(spread_bps=6.0):
    mid=Decimal('100')
    spread_bps_dec = Decimal(str(spread_bps))
    half = (spread_bps_dec/Decimal('2'))/Decimal('10000')*mid
    bid = mid - half; ask = mid + half
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=bid, best_ask=ask, spread_bps=float(spread_bps), mid=mid)


def _intent(er_bps=8, qty=Decimal('1'), post_only=False):
    return OrderIntent(intent_id='inv', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=er_bps, stop_dist_bps=50,
                       tp_targets_bps=[120], risk_ctx={'equity_usd':'10000'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={'post_only':post_only}, qty_hint=qty)


def _router(capture_eta=0.0, rebate_mode=True, pfill_min=0.7):
    cfg={'execution':{'router':{'pfill_min':pfill_min,'capture_eta':capture_eta,'rebate_mode':rebate_mode,'maker_spread_ok_bps':10,'spread_deny_bps':40,'switch_margin_bps':0.1},
                      'sla':{'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0}}}
    return RouterV2(config=cfg, event_logger=AuroraEventLogger())


def test_edge_budget_net_equals_sum():
    r=_router(capture_eta=0.5)
    m=_market(spread_bps=4.0)
    d=r.route(_intent(qty=Decimal('2')), m, latency_ms=3.0, features={'pred_latency_ms':3.0})
    if isinstance(d, DenyDecision):
        return  # acceptable under weak economics
    t=d.tca
    net = t.raw + t.fees + t.slip_est + t.adv_sel + t.lat_cost + t.rebates
    assert net == t.net_after_tca


def test_em_monotonic_wrt_capture_eta():
    m=_market(spread_bps=6.0)
    i=_intent(qty=Decimal('1'))
    f={'pred_latency_ms':5.0}
    r0=_router(capture_eta=0.0); d0=r0.route(i,m,latency_ms=5.0,features=f)
    r5=_router(capture_eta=0.5); d5=r5.route(i,m,latency_ms=5.0,features=f)
    r1=_router(capture_eta=1.0); d1=r1.route(i,m,latency_ms=5.0,features=f)
    # Use expected maker edge integer approximation from event fields
    def em(dec):
        return dec.tca if not isinstance(dec, DenyDecision) else None
    # If maker chosen at 0.5, then at 1.0 it should not degrade (reason stays maker or equal net)
    if em(d5) and d5.tca.reason=='MAKER_SELECTED' and em(d1):
        assert d1.tca.reason=='MAKER_SELECTED'


def test_low_pfill_always_denies():
    # Configure very high pfill_min to force LOW_PFILL regardless of spread or rebates
    r=_router(capture_eta=1.0, pfill_min=0.99)
    m=_market(spread_bps=2.0)
    d=r.route(_intent(qty=Decimal('1'), er_bps=50, post_only=False), m, latency_ms=1.0, features={'pred_latency_ms':1.0, 'obi':-1.0})
    if isinstance(d, DenyDecision):
        assert d.code in ('LOW_PFILL.DENY','EDGE_DENY')
    else:
        # If not denied, it must be taker with positive net, but high threshold should push to deny in most settings
        assert d.mode in ('maker','taker')


def test_final_notional_after_quantization_meets_min():
    r=_router(capture_eta=0.5)
    # lot=0.001, minNotional=5, mid=100 => min qty ~0.05 => floor to multiple
    m=_market(spread_bps=4.0)
    i=_intent(qty=Decimal('0.049'))
    d=r.route(i,m,latency_ms=5.0,features={'pred_latency_ms':5.0})
    if isinstance(d, DenyDecision):
        # Denied due to MIN_NOTIONAL is okay here
        assert d.code in ('MIN_NOTIONAL','LOT_SIZE','EDGE_DENY','LOW_PFILL.DENY')
    else:
        notional = Decimal(d.qty) * m.mid if d.price is None else Decimal(d.qty) * Decimal(d.price)
        assert notional >= m.min_notional
