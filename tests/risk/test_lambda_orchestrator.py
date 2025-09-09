from core.risk.multipliers import LambdaOrchestrator

def test_lambdas_monotonic_and_ranges():
    cfg={'kelly':{'multipliers':{
        'cal':{'ece_warn':0.04,'ece_bad':0.08},
        'reg':{'trend':1.0,'grind':0.8,'chaos':0.6},
        'liq':{'spread_bps_breaks':[5,10],'lambdas':[1.0,0.8,0.6]},
        'dd': {'dd_warn':0.05,'dd_bad':0.10,'lambdas':[1.0,0.7,0.4]},
        'lat':{'p95_ms_breaks':[200,500],'lambdas':[1.0,0.8,0.6]},
    }}}
    lo=LambdaOrchestrator(cfg)
    risk_ctx={'drawdown_frac':0.03}
    # good
    L1=lo.compute({}, risk_ctx, {'half_spread_bps':2.0,'latency_p95_ms':150,'ece':0.01,'regime':'trend'})
    # worse
    L2=lo.compute({}, risk_ctx, {'half_spread_bps':7.0,'latency_p95_ms':300,'ece':0.06,'regime':'grind'})
    # worst
    L3=lo.compute({}, {'drawdown_frac':0.2}, {'half_spread_bps':12.0,'latency_p95_ms':800,'ece':0.1,'regime':'chaos'})
    assert 0< L1['cal']<=1.25 and 0< L2['cal']<=L1['cal'] and 0< L3['cal']<=L2['cal']
    assert 0< L1['liq']<=1.25 and 0< L2['liq']<=L1['liq'] and 0< L3['liq']<=L2['liq']
    assert 0< L1['lat']<=1.25 and 0< L2['lat']<=L1['lat'] and 0< L3['lat']<=L2['lat']
    assert 0< L1['dd']<=1.25 and 0< L2['dd']<=L1['dd'] and 0< L3['dd']<=L2['dd']
