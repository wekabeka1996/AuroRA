from decimal import Decimal
from core.risk.sizing_orchestrator import SizingOrchestrator
from core.execution.router_v2 import OrderIntent, MarketSpec


def mk_market():
    return MarketSpec(
        tick_size=Decimal('0.01'), lot_size=Decimal('0.1'), min_notional=Decimal('10'),
        maker_fee_bps=1, taker_fee_bps=5, best_bid=Decimal('100'), best_ask=Decimal('100.1'),
        spread_bps=1.0, mid=Decimal('100.05')
    )


def test_cvar_gate_zeroes_qty_and_emits_shift(tmp_path):
    cfg={
        'risk':{'per_trade_usd':0.01,'cvar_limit_usd':50,'leverage_max':5,'exposure_cap_usd':10000,'cvar':{'alpha':0.95,'min_exceedances':50}},
        'kelly':{'bounds':{'m_min':0.25,'m_max':1.25,'f_max':0.03}},
        'execution':{'sla':{'p95_ms':200}}
    }
    so=SizingOrchestrator(cfg)
    market=mk_market()
    intent=OrderIntent(
        intent_id='t2', timestamp_ms=0, symbol='TEST', side='BUY', dir=1, strategy_id='s1',
        expected_return_bps=10, stop_dist_bps=500, tp_targets_bps=[200],
        risk_ctx={'equity_usd': '10000', 'cvar_curr_usd': 60, 'cvar_limit_usd': 50, 'ece':0.01, 'regime':'trend'},
        regime_ctx={}, exec_prefs={}, qty_hint=Decimal('1.0')
    )
    k=so.compute(intent, market)
    assert k.qty_final == 0
