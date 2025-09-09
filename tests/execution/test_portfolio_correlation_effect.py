from __future__ import annotations
from decimal import Decimal
import numpy as np
from core.risk.sizing_orchestrator import SizingOrchestrator
from core.execution.router_v2 import OrderIntent, MarketSpec
from core.aurora_event_logger import AuroraEventLogger


class DummyLogger(AuroraEventLogger):
    def __init__(self):
        super().__init__(path='logs/test_events_portfolio.jsonl')
        self.events = []
    def emit(self, event_code=None, details=None, **kwargs):
        self.events.append((event_code, details))


def base_cfg():
    return {
        'risk':{
            'per_trade_usd': 0.0001,
            'cvar_limit_usd': 1_000_000,
            'leverage_max': 1000,
            'exposure_cap_usd': 1_000_000,
            'cvar': {'alpha':0.95,'min_exceedances':50}
        },
        'kelly':{
            'bounds':{'m_min':0.25,'m_max':1.25,'f_max':1.0},
            'multipliers':{
                'cal':{'ece_warn':0.02,'ece_bad':0.08},
                'reg':{'trend':1.0,'grind':1.0,'chaos':1.0},
                'liq':{'spread_bps_breaks':[5,10],'lambdas':[1.0,1.0,1.0]},
                'dd': {'dd_warn':0.05,'dd_bad':0.10,'lambdas':[1.0,1.0,1.0]},
                'lat':{'p95_ms_breaks':[200,500],'lambdas':[1.0,1.0,1.0]},
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


def mk_intent(equity: Decimal, stop_bps=200):
    return OrderIntent(
        intent_id='p1', timestamp_ms=0, symbol='TEST', side='BUY', dir=1, strategy_id='s1',
        expected_return_bps=10, stop_dist_bps=stop_bps, tp_targets_bps=[200],
        risk_ctx={'equity_usd': str(equity), 'ece':0.0, 'regime':'trend'},
        regime_ctx={}, exec_prefs={}, qty_hint=None
    )


def test_portfolio_correlation_effect_qty_and_fport():
    logger = DummyLogger()
    so = SizingOrchestrator(base_cfg(), event_logger=logger)
    market = mk_market()
    equity = Decimal('100000')

    # Portfolio with 2 assets incl TEST; PVs
    pv = np.array([50_000.0, 30_000.0])
    symbols = ['TEST','OTHER']
    # Variance baseline
    var = np.array([0.02, 0.02])
    # Two covariances with different correlations
    rho_high = 0.8
    rho_low = 0.1
    cov_high = np.array([[var[0], rho_high*np.sqrt(var[0]*var[1])], [rho_high*np.sqrt(var[0]*var[1]), var[1]]])
    cov_low  = np.array([[var[0], rho_low *np.sqrt(var[0]*var[1])], [rho_low *np.sqrt(var[0]*var[1]), var[1]]])

    intent_h = mk_intent(equity)
    intent_l = mk_intent(equity)

    # Attach portfolio contexts
    intent_h.risk_ctx.update({'portfolio_symbols': symbols, 'portfolio_cov': cov_high.tolist(), 'portfolio_pv_usd': pv.tolist()})
    intent_l.risk_ctx.update({'portfolio_symbols': symbols, 'portfolio_cov': cov_low.tolist(),  'portfolio_pv_usd': pv.tolist()})

    k_h = so.compute(intent_h, market)
    # Reset logger capture for second run
    logger.events.clear()
    k_l = so.compute(intent_l, market)

    assert k_h.qty_final < k_l.qty_final, f"qty_high({k_h.qty_final}) !< qty_low({k_l.qty_final})"

    # Check XAI events for f_port differences
    # For the second compute, logger contains only events from low corr; to get both, recompute capturing events
    logger.events.clear()
    so.compute(intent_h, market)
    events_h = list(logger.events)
    logger.events.clear()
    so.compute(intent_l, market)
    events_l = list(logger.events)

    fph = next((e[1]['f_port'] for e in events_h if e[0]=='KELLY.APPLIED'), None)
    fpl = next((e[1]['f_port'] for e in events_l if e[0]=='KELLY.APPLIED'), None)
    assert fph is not None and fpl is not None
    assert fph < fpl, f"f_port high({fph}) !< f_port low({fpl})"
