from decimal import Decimal
from core.risk.sizing_orchestrator import SizingOrchestrator
from core.execution.router_v2 import OrderIntent, MarketSpec
from core.aurora_event_logger import AuroraEventLogger

class DummyLogger(AuroraEventLogger):
    def __init__(self):
        super().__init__(path='logs/test_events.jsonl')
        self.events=[]
    def emit(self, event_code=None, details=None, **kwargs):
        self.events.append((event_code, details))


def base_cfg():
    return {
        'risk':{
            'per_trade_usd': 0.01,
            'cvar_limit_usd': 1000,
            'leverage_max': 5,
            'exposure_cap_usd': 10000,
            'cvar': {'alpha':0.95,'min_exceedances':50}
        },
        'kelly':{
            'bounds':{'m_min':0.25,'m_max':1.25,'f_max':0.03},
            'multipliers':{
                'cal':{'ece_warn':0.02,'ece_bad':0.08},
                'reg':{'trend':1.0,'grind':0.8,'chaos':0.6},
                'liq':{'spread_bps_breaks':[5,10],'lambdas':[1.0,0.8,0.6]},
                'dd': {'dd_warn':0.05,'dd_bad':0.10,'lambdas':[1.0,0.7,0.4]},
                'lat':{'p95_ms_breaks':[200,500],'lambdas':[1.0,0.8,0.6]},
            }
        },
        'execution':{'sla':{'p95_ms':200}}
    }


def mk_market():
    return MarketSpec(
        tick_size=Decimal('0.01'), lot_size=Decimal('0.1'), min_notional=Decimal('10'),
        maker_fee_bps=1, taker_fee_bps=5, best_bid=Decimal('100'), best_ask=Decimal('100.1'),
        spread_bps=1.0, mid=Decimal('100.05')
    )


def mk_intent(stop_bps=100, qty_hint=None, equity=Decimal('10000')):
    return OrderIntent(
        intent_id='t1', timestamp_ms=0, symbol='TEST', side='BUY', dir=1, strategy_id='s1',
        expected_return_bps=10, stop_dist_bps=stop_bps, tp_targets_bps=[200],
        risk_ctx={'equity_usd': str(equity), 'ece':0.01, 'regime':'trend'},
        regime_ctx={}, exec_prefs={}, qty_hint=qty_hint
    )


def test_m_lambda_influences_qty():
    logger=DummyLogger()
    so=SizingOrchestrator(base_cfg(), event_logger=logger)
    market = mk_market()
    intent = mk_intent(stop_bps=200)
    # compute with low latency and small spread (M near 1)
    k1=so.compute(intent, market)
    # worse micro conditions: higher spread and latency
    so.cfg['execution']['sla']['p95_ms']=600
    intent.risk_ctx['ece']=0.09
    market.spread_bps=12.0
    k2=so.compute(intent, market)
    assert k2.qty_final <= k1.qty_final


def test_min_notional_bump_and_caps():
    logger=DummyLogger()
    cfg=base_cfg()
    cfg['risk']['per_trade_usd']=0.0001  # extremely small base size
    so=SizingOrchestrator(cfg, event_logger=logger)
    market = mk_market()
    # small equity to trigger caps interplay
    intent = mk_intent(stop_bps=50, equity=Decimal('100'))
    k=so.compute(intent, market)
    # Either bumped to meet min_notional or zero if impossible
    assert (k.qty_final*market.mid >= market.min_notional) or (k.qty_final==0)
