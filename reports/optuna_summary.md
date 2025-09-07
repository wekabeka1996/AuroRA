# Optuna Hyperparameter Optimization Results

**Study**: aurora_real_v1
**Best Trial**: 1 (Score: 0.2509)
**Total Trials**: 5

## Best Parameters

- **execution.router.spread_limit_bps**: 4
- **execution.sla.max_latency_ms**: 104
- **reward.be_break_even_bps**: 2
- **reward.stop_loss_bps**: 73
- **reward.take_profit_bps**: 38
- **reward.ttl_minutes**: 79
- **sizing.kelly_scaler**: 0.3793972738151323
- **sizing.limits.leverage_max**: 5
- **sizing.limits.max_notional_usd**: 780
- **tca.adverse_window_s**: 8
- **universe.ranking.top_n**: 16

## Best Metrics

- **sharpe**: 0.4733775330376978
- **return_adj**: 0.07152221955325982
- **tca_slip_bps**: 2.8953287121024367
- **tca_fees_bps**: 0.6115824924614749
- **tca_adv_bps**: 2.7170519366222194
- **cvar95**: -0.0905312835952421
- **max_dd**: 0.16715668579211643
- **latency_p99**: 112.82657109288384
- **deny_rate**: 0.24469111713179542
- **ece**: 0.032524947839765964
- **xai_top_why**: ['factor_0', 'factor_1', 'factor_2']
