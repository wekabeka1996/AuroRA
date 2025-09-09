from __future__ import annotations
from src.aurora.governance.gate import GovernanceGate
from src.aurora.governance.models import PerfSnapshot
from src.aurora.governance.alpha_ledger import AlphaLedger
from core.aurora_event_logger import AuroraEventLogger


def cfg():
    return {
        'governance':{
            'soak':{'min_minutes_canary':60,'min_trades_canary':300},
            'thresholds':{
                'sr_min_live':2.0,
                'p_glr_max_live':0.05,
                'edge_mean_bps_min':0.0,
                'sla_p95_ms_max':500,
                'sla_breach_rate_max':0.01,
                'xai_missing_rate_max':0.01,
            },
            'alpha':{'budget_total':0.1,'spend_canary_to_live':0.02,'spend_shadow_to_canary':0.01}
        }
    }


def perf_base():
    return PerfSnapshot(
        trades=400,
        window_ms=60*60_000,
        sr=2.5,
        pvalue_glr=0.03,
        sprt_pass=True,
        edge_mean_bps=1.0,
        latency_p95_ms=200,
        xai_missing_rate=0.0,
        cvar_breach=False,
        sla_breach_rate=0.0,
    )


def test_shadow_to_canary_ok():
    gate = GovernanceGate(cfg(), event_logger=AuroraEventLogger())
    p = perf_base()
    d = gate.evaluate(p, 'shadow', now_ms=0)
    assert d.mode == 'canary'
    assert d.alpha_spent == 0.01
    assert d.allow is True


def test_canary_to_live_requires_soak():
    gate = GovernanceGate(cfg(), event_logger=AuroraEventLogger())
    p = perf_base()
    p.trades = 200  # not enough
    d = gate.evaluate(p, 'canary', now_ms=0)
    assert d.mode == 'canary'


def test_canary_to_live_ok():
    gate = GovernanceGate(cfg(), event_logger=AuroraEventLogger())
    p = perf_base()
    d = gate.evaluate(p, 'canary', now_ms=0)
    assert d.mode == 'live'
    assert d.alpha_spent == 0.02


def test_redflag_to_shadow():
    gate = GovernanceGate(cfg(), event_logger=AuroraEventLogger())
    p = perf_base()
    p.cvar_breach = True
    d = gate.evaluate(p, 'live', now_ms=0)
    assert d.mode == 'shadow'


def test_alpha_budget_exhausted():
    # Set budget low, spend once then block second
    conf = cfg()
    conf['governance']['alpha']['budget_total'] = 0.01
    gate = GovernanceGate(conf, event_logger=AuroraEventLogger())
    p = perf_base()
    d1 = gate.evaluate(p, 'shadow', now_ms=0)
    assert d1.mode == 'canary'
    # Next promotion should be blocked due to budget
    d2 = gate.evaluate(p, 'canary', now_ms=0)
    assert d2.mode == 'canary'
    assert d2.reason == 'alpha_budget_exhausted'
