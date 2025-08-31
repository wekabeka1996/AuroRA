PR-A: PortfolioOptimizer compatibility shim

- Added backwards-compatible constructor parameters to fallback PortfolioOptimizer:
  `method`, `cvar_alpha`, `cvar_limit`, `gross_cap`, `max_weight`.
- Preserves previous behavior of `optimize()` returning an empty allocation.
- Added lightweight smoke test `tests/unit/test_portfolio_optimizer_smoke.py`.
