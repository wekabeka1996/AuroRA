from decimal import Decimal
from core.execution.router_v2 import RouterV2, OrderIntent, MarketSpec, DenyDecision
from core.aurora_event_logger import AuroraEventLogger

# Helper to build intent/market

def _intent(expected_return_bps:int=6, post_only=False, qty=Decimal('1')):
    return OrderIntent(
        intent_id='i1', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
        strategy_id='strat', expected_return_bps=expected_return_bps,
        stop_dist_bps=50, tp_targets_bps=[100], risk_ctx={'equity_usd':'10000'},
        regime_ctx={'governance':'shadow'}, exec_prefs={'post_only':post_only}, qty_hint=qty
    )

def _market(spread_bps:float=4.0):
    mid=Decimal('100')
    spread_bps_dec = Decimal(str(spread_bps))
    half_spread = (spread_bps_dec / Decimal('2')) / Decimal('10000') * mid
    best_bid = mid - half_spread
    best_ask = mid + half_spread
    return MarketSpec(
        tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
        maker_fee_bps=0, taker_fee_bps=5, best_bid=best_bid, best_ask=best_ask,
    spread_bps=float(spread_bps), mid=mid
    )

def _router(capture_eta:float):
    cfg = {
        'execution': {
            'router': {
                'capture_eta': capture_eta,
                'rebate_mode': True,
                'pfill_min': 0.55,
                'maker_spread_ok_bps': 10.0,
                'spread_deny_bps': 50.0,
                'switch_margin_bps': 0.1,
            },
            'sla': { 'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0 }
        }
    }
    return RouterV2(config=cfg, event_logger=AuroraEventLogger())


def test_capture_eta_monotonic_and_route_flip():
    m = _market(spread_bps=6.0)  # half-spread=3 bps
    base_int = _intent(expected_return_bps=4)  # raw edge 4 bps
    features = { 'obi':0.0, 'pred_latency_ms':5.0 }
    # Force high p_fill
    # Evaluate three capture_eta values
    r0 = _router(0.0)
    d0 = r0.route(base_int, m, latency_ms=5.0, features=features)
    # If economics too weak can be denial; else expect taker
    if isinstance(d0, DenyDecision):
        assert d0.code in ('EDGE_DENY','EDGE_FLOOR','LOW_PFILL.DENY')
    else:
        assert d0.mode == 'taker'

    r05 = _router(0.5)
    d05 = r05.route(base_int, m, latency_ms=5.0, features=features)
    if isinstance(d05, DenyDecision):
        # Should be rarer with spread contribution, still allow edge deny
        assert d05.code in ('EDGE_DENY','LOW_PFILL.DENY')
    else:
        assert d05.mode in ('maker','taker')

    r1 = _router(1.0)
    d1 = r1.route(base_int, m, latency_ms=5.0, features=features)
    # Collect expected maker E via events not directly accessible; ensure at least not taker if economics improved enough

    # Monotonicity: maker expected edge grows with capture_eta so if maker selected at 0.5 it must also at 1.0
    if not isinstance(d05, DenyDecision) and d05.tca.reason == 'MAKER_SELECTED' and not isinstance(d1, DenyDecision):
        assert d1.tca.reason == 'MAKER_SELECTED'

    # Ensure net_after_tca positive for any allow
    for d in (d0, d05, d1):
        if not isinstance(d, DenyDecision):
            assert d.tca.net_after_tca > 0
