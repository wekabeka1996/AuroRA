from core.universe.ranking import UniverseRanker


def test_ranking_by_liquidity_and_thresholds():
    # Weights emphasize L only; low dwell so membership can flip immediately
    r = UniverseRanker(wL=1.0, wS=0.0, wP=0.0, wR=0.0, add_thresh=0.5, drop_thresh=0.4, min_dwell=1, ema_alpha=1.0)

    r.update_metrics("A", liquidity=100.0, spread_bps=10.0, p_fill=0.5, regime_flag=1.0)
    r.update_metrics("B", liquidity=200.0, spread_bps=10.0, p_fill=0.5, regime_flag=1.0)
    r.update_metrics("C", liquidity=300.0, spread_bps=10.0, p_fill=0.5, regime_flag=1.0)

    ranked = r.rank(top_k=2)
    # Expect order by liquidity (C highest, then B)
    assert [x.symbol for x in ranked] == ["C", "B"]
    # Active should include B and C (scores ≈ 0.5 and 1.0), but not A (≈ 0.0)
    assert all(x.active for x in ranked)


def test_ranking_spread_inversion():
    # Emphasize spread only, lower is better after inversion
    r = UniverseRanker(wL=0.0, wS=1.0, wP=0.0, wR=0.0, add_thresh=0.0, drop_thresh=0.0, min_dwell=1, ema_alpha=1.0)

    r.update_metrics("S1", liquidity=100.0, spread_bps=2.0, p_fill=0.5, regime_flag=1.0)
    r.update_metrics("S2", liquidity=100.0, spread_bps=1.0, p_fill=0.5, regime_flag=1.0)
    r.update_metrics("S3", liquidity=100.0, spread_bps=5.0, p_fill=0.5, regime_flag=1.0)

    ranked = r.rank(top_k=3)
    # smallest spread first
    assert [x.symbol for x in ranked][:1] == ["S2"]
