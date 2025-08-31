def test_portfolio_optimizer_smoke():
    from core.sizing.portfolio import PortfolioOptimizer

    # instantiate with no args
    opt1 = PortfolioOptimizer()
    assert hasattr(opt1, "method")
    assert hasattr(opt1, "cvar_alpha")

    # instantiate with kwargs expected by tests
    opt2 = PortfolioOptimizer(method="lw_shrinkage", cvar_alpha=0.95, cvar_limit=0.1, gross_cap=1.0, max_weight=0.3)
    assert opt2.method == "lw_shrinkage"
    assert abs(opt2.cvar_alpha - 0.95) < 1e-9

    # basic optimize call returns mapping
    alloc = opt2.optimize([[1.0]], [0.01])
    assert isinstance(alloc, dict) or isinstance(alloc, (list, tuple))
