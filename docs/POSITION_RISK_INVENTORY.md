# Position & Risk Management Inventory

## Sizing Models

### Kelly Criterion (Primary)
- **Model**: Kelly binary criterion with risk aversion and clipping
- **Formula**: `f* = (b*p - (1-p)) / b` where `b = rr`, with risk aversion multiplier
- **Features**:
  - Risk aversion scaling: `f = f* / risk_aversion`
  - Clipping bounds: configurable min/max fractions (default 0.0-0.2)
  - DD haircut: reduces position size during drawdowns
  - Hysteresis: prevents small oscillations
  - Bucket sizing: discrete position sizes
  - Time guards: minimum interval between resizes
- **Files**:
  - `core/sizing/kelly.py:28-75` - `kelly_binary()` function
  - `core/sizing/kelly.py:77-95` - `kelly_mu_sigma()` for continuous returns
  - `core/sizing/kelly.py:97-130` - `fraction_to_qty()` converts Kelly fraction to executable quantity
  - `core/sizing/kelly.py:132-155` - `dd_haircut_factor()` for drawdown adjustments
  - `core/sizing/kelly.py:157-170` - `apply_dd_haircut_to_kelly()`
  - `core/sizing/kelly.py:172-220` - `SizingStabilizer` class with hysteresis/bucket/time guards
  - `skalp_bot/runner/run_live_aurora.py:222-226` - Kelly sizer configuration
  - `skalp_bot/runner/run_live_aurora.py:305-306` - Kelly fraction calculation

### Portfolio Optimization (Secondary)
- **Model**: Mean-variance optimization with NumPy fallback
- **Features**:
  - Gross exposure cap
  - Max weight per position
  - Long-only constraint option
  - Leverage scaling
- **Files**:
  - `core/sizing/portfolio.py:58-175` - `PortfolioOptimizer` class
  - `skalp_bot/runner/run_live_aurora.py:29` - `PortfolioOptimizer` import
  - `skalp_bot/runner/run_live_aurora.py:218` - Portfolio config initialization

## SL/TP Mechanisms

### Take Profit (TP)
- **Implementation**: Simple threshold-based TP for LONG positions only
- **Logic**: `mid >= entry_price * (1.0 + tp_pct)`
- **Limitations**:
  - Only for LONG positions
  - No SHORT TP
  - Fixed percentage threshold
  - No trailing or partial TP
- **Files**:
  - `skalp_bot/runner/run_live_aurora.py:241-245` - TP configuration
  - `skalp_bot/runner/run_live_aurora.py:522-523` - TP condition check
  - `skalp_bot/runner/run_live_aurora.py:535-540` - TP execution logic

### Stop Loss (SL)
- **Status**: NOT IMPLEMENTED
- **Missing Features**:
  - No bracket orders (entry + SL + TP)
  - No trailing SL
  - No break-even (BE) adjustments
  - No SL for SHORT positions

### Partial TP & Advanced Features
- **Status**: NOT IMPLEMENTED
- **Missing Features**:
  - No partial TP (scaling out)
  - No pyramiding (adding to positions)
  - No trailing mechanisms
  - No dynamic SL adjustments

## Risk Limits

### Exposure Limits
- **Gross Exposure**: Configurable via `PortfolioOptimizer.gross_cap`
- **Per-Symbol Caps**: Via `max_weight` parameter in portfolio optimizer
- **Files**:
  - `core/sizing/portfolio.py:166-170` - Gross exposure scaling
  - `core/sizing/portfolio.py:158-165` - Max weight clipping

### Leverage Limits
- **Per-Symbol Leverage**: Configurable via exchange config
- **Validation**: Margin requirements checked in `fraction_to_qty()`
- **Files**:
  - `core/sizing/kelly.py:97-130` - Leverage consideration in quantity calculation
  - `skalp_bot/exch/ccxt_binance.py:151-152` - Leverage setting
  - `configs/aurora/testnet.yaml` - `leverage: 25`

### Position Limits
- **Max Concurrent Positions**: Configurable via governance gates
- **Default**: 999 (effectively unlimited)
- **Files**:
  - `aurora/governance.py:78` - `max_concurrent_positions` check
  - `tests/test_governance_guards.py:20` - Test configuration

### Other Limits
- **Daily Drawdown**: Configurable percentage limit
- **CVaR Limits**: Conditional Value at Risk thresholds
- **Spread/Latency Guards**: Market microstructure limits
- **Files**:
  - `aurora/governance.py:55-65` - DD and CVaR checks
  - `aurora/governance.py:67-75` - Market microstructure guards

## Reconciliation

### Position Reconciliation
- **Implementation**: Basic position tracking via exchange state
- **Features**:
  - Position state maintained in runner
  - Fill tracking via `PartialSlicer`
  - Basic balance checks
- **Limitations**:
  - No automated reconciliation with exchange
  - No drift detection
  - No position recovery mechanisms
- **Files**:
  - `core/execution/partials.py` - Fill tracking and remaining quantity
  - `skalp_bot/runner/run_live_aurora.py` - Position state management
  - `tests/e2e/test_trade_flow_simulator.py:100-105` - Reconciliation testing

### Balance Reconciliation
- **Status**: Limited
- **Missing Features**:
  - No periodic balance sync with exchange
  - No reconciliation reports
  - No handling of exchange-specific adjustments

## Configuration Sources

### YAML Configuration
- `configs/aurora/testnet.yaml`:
  - `leverage: 25`
  - `use_futures: true`
- `profiles/btc_production_testnet.yaml`:
  - Risk thresholds and sizing parameters

### Environment Variables
- `AURORA_TP_PCT`: TP percentage threshold
- `AURORA_MAX_CONCURRENT`: Max concurrent positions override

### Code Defaults
- Kelly risk aversion: 1.0
- Kelly clip bounds: (0.0, 0.2)
- TP percentage: 0.00001 (~1 bp)
- Max concurrent positions: 999</content>
<parameter name="filePath">c:\Users\user\Music\Aurora\docs\POSITION_RISK_INVENTORY.md