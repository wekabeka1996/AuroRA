from decimal import Decimal
from core.execution.execution_service import ExecutionService
from core.execution.router_v2 import OrderIntent, MarketSpec, DenyDecision
from core.aurora_event_logger import AuroraEventLogger


def _svc():
    cfg={'execution':{'router':{'pfill_min':0.6,'capture_eta':0.4,'rebate_mode':True,'maker_spread_ok_bps':10,'spread_deny_bps':40,'switch_margin_bps':0.1},
                      'sla':{'kappa_bps_per_ms':0.0,'max_latency_ms':250,'edge_floor_bps':0.0}},
         'risk':{'per_trade_usd':0.01}}
    return ExecutionService(config=cfg, event_logger=AuroraEventLogger())


def _market(lot_size=Decimal('0.001')):
    mid=Decimal('100'); best_bid=Decimal('99.99'); best_ask=Decimal('100.01')
    spread_bps=float((best_ask-best_bid)/((best_ask+best_bid)/2)*10000)
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=lot_size, min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=best_bid, best_ask=best_ask, spread_bps=spread_bps, mid=mid)


def _intent_zero_by_minnotional():
    # Small equity and large stop -> q_base extremely small; minNotional bump may still be < min leading to zero
    return OrderIntent(intent_id='z0', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=10, stop_dist_bps=10000,
                       tp_targets_bps=[200], risk_ctx={'equity_usd':'1'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={}, qty_hint=None)


def _intent_zero_by_cvar():
    # CVaR already above limit -> sizing should return zero
    return OrderIntent(intent_id='z1', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=10, stop_dist_bps=100,
                       tp_targets_bps=[200], risk_ctx={'equity_usd':'1000','cvar_curr_usd':'60','cvar_limit_usd':'55','delta_cvar_per_unit_usd':'0.5'},
                       regime_ctx={'governance':'shadow'}, exec_prefs={}, qty_hint=None)


def test_size_zero_by_minnotional():
    svc=_svc(); m=_market(lot_size=Decimal('0.1')); intent=_intent_zero_by_minnotional()
    dec=svc.place(intent, m, features={'pred_latency_ms':5.0}, measured_latency_ms=5.0)
    assert isinstance(dec, DenyDecision)
    assert dec.code == 'SIZE_ZERO.DENY'


def test_size_zero_by_cvar():
    svc=_svc(); m=_market(); intent=_intent_zero_by_cvar()
    dec=svc.place(intent, m, features={'pred_latency_ms':5.0}, measured_latency_ms=5.0)
    assert isinstance(dec, DenyDecision)
    assert dec.code == 'SIZE_ZERO.DENY'
