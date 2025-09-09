from decimal import Decimal
from core.risk.sizing_orchestrator import SizingOrchestrator
from core.execution.router_v2 import MarketSpec, OrderIntent
from core.aurora_event_logger import AuroraEventLogger


def _market():
    return MarketSpec(tick_size=Decimal('0.01'), lot_size=Decimal('0.001'), min_notional=Decimal('5'),
                      maker_fee_bps=0, taker_fee_bps=5, best_bid=Decimal('99.99'), best_ask=Decimal('100.01'), spread_bps=2.0, mid=Decimal('100'))


def _intent(equity_usd:str, cvar_curr:str, d_cvar_per_unit:str, cvar_limit:str='50'):
    return OrderIntent(intent_id='ic', timestamp_ms=0, symbol='BTCUSDT', side='BUY', dir=1,
                       strategy_id='s', expected_return_bps=12, stop_dist_bps=120,
                       tp_targets_bps=[240], risk_ctx={'equity_usd':equity_usd,'cvar_curr_usd':cvar_curr,'delta_cvar_per_unit_usd':d_cvar_per_unit,'cvar_limit_usd':cvar_limit},
                       regime_ctx={'governance':'shadow'}, exec_prefs={}, qty_hint=None)


def test_cvar_shift_event_and_scaling(tmp_path):
    cfg={'risk':{'per_trade_usd':0.01},'kelly':{'bounds':{'m_min':0.5,'m_max':1.0}}}
    # Use dedicated logger writing to temp file
    log_path = tmp_path / 'events.jsonl'
    logger = AuroraEventLogger(path=log_path)
    sz=SizingOrchestrator(cfg, event_logger=logger)
    m=_market()
    intent=_intent('1000','60','0.5','55')  # already above limit, scaling expected
    k=sz.compute(intent,m)
    # After scaling we should not increase CVaR beyond current breach; stub policy: if already above limit -> qty becomes 0.
    # Reconstruct projected (baseline capped at limit for evaluation semantics)
    cvar_curr=Decimal('60'); d=Decimal('0.5')
    projected = min(cvar_curr, Decimal('55')) + d * k.qty_final
    assert projected <= Decimal('55') + Decimal('0.5')  # epsilon 0.5
    content = log_path.read_text(encoding='utf-8')
    assert 'CVAR.SHIFT' in content
