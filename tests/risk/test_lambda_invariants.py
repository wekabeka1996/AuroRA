from core.risk.multipliers import LambdaOrchestrator


def test_lambda_keys_and_bounds():
    cfg={'kelly':{'multipliers':{}}}
    lo=LambdaOrchestrator(cfg)
    risk_ctx={'drawdown_frac':0.0}
    regimes=['trend','grind','chaos','unknown']
    hs=[0,3,6,12]
    lats=[50,200,400,800]
    eces=[0.0,0.02,0.06,0.12]
    for rg in regimes:
        for h in hs:
            for lt in lats:
                for e in eces:
                    L=lo.compute({}, risk_ctx, {'regime':rg,'half_spread_bps':h,'latency_p95_ms':lt,'ece':e})
                    for k in ('cal','reg','liq','dd','lat'):
                        assert k in L
                        v=L[k]
                        assert isinstance(v,(int,float))
                        assert v>0
                        assert v<=1.25
