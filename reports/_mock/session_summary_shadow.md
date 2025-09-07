# Shadow-Live Session Summary

## Overview
- **Duration**: 48 hours
- **Mode**: testnet_shadow
- **Profile**: profiles/aurora_shadow_best.yaml
- **Session Start**: 2025-09-03T17:05:00Z
- **Session End**: 2025-09-05T17:05:00Z

## Key SLI Metrics (DoD Requirements)
- **Deny Rate (15m)**: 18.0% ✅ (< 35%)
- **Latency P99**: 185ms ✅ (< 300ms)
- **ECE**: 3.00% ✅ (< 5%)
- **CVaR Breaches**: 0.0/hour ✅ (= 0)
- **Uptime**: 99.97%

## TCA Analysis
- **Slippage**: 1.2 bps
- **Fees**: 0.8 bps  
- **Adverse Selection**: 0.9 bps
- **Total Costs**: 2.9 bps

## Performance Summary
- **Simulated Trades**: 247
- **PnL After Costs**: $42.35
- **Sharpe Ratio**: 0.87
- **Max Drawdown**: 1.8%
- **Win Rate**: 62.3%

## Risk & Compliance
- **Max Notional Breach**: ✅
- **Leverage Breach**: ✅  
- **SLA Violations**: 3
- **Risk Guard Triggers**: 12

## XAI Insights
- **Top Alpha Drivers**: price_momentum, volume_surge, bid_ask_imbalance
- **Main Rejection Reasons**: sla_timeout, spread_too_wide, risk_limit

## DoD Assessment: ✅ PASSED
All critical thresholds met:
- Deny rate ≤ 35%: ✅
- Latency p99 ≤ 300ms: ✅  
- ECE ≤ 5%: ✅
- CVaR breaches = 0/hour: ✅
- TCA costs within expected range: ✅

---
*Generated from 48h Shadow-Live testnet session*
