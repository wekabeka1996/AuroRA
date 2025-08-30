"""
Test for UniverseRanker None input handling
"""
from repo.core.universe.ranking import UniverseRanker


def test_none_inputs_are_coerced():
    """Test that None inputs are properly coerced to numeric defaults"""
    r = UniverseRanker()
    
    # Test update_metrics with None values
    r.update_metrics("BTCUSDT", liquidity=None, spread_bps=None, p_fill=None, regime_flag=None)
    
    # Should not raise an exception and should return a valid ranking
    ranked = r.rank()
    assert isinstance(ranked, list)
    
    # Should have one entry
    assert len(ranked) == 1
    assert ranked[0].symbol == "BTCUSDT"
    
    # All metrics should be coerced to numeric values (defaults)
    # Since all inputs were None, they should get default values of 0.0
    # The score will be based on the robust scaling of these values
    assert ranked[0].score >= 0.0  # Score should be non-negative
    assert ranked[0].active == False  # Score should be below add threshold


def test_mixed_none_and_values():
    """Test mixing None and actual values"""
    r = UniverseRanker()
    
    # Mix None and actual values
    r.update_metrics("ETHUSDT", 
                    liquidity=1000000.0,    # Good liquidity
                    spread_bps=None,        # Should default to 0.0
                    p_fill=0.8,             # Good fill probability  
                    regime_flag=None)       # Should default to 0.0
    
    ranked = r.rank()
    assert len(ranked) == 1
    assert ranked[0].symbol == "ETHUSDT"
    
    # Score should be positive due to liquidity and p_fill contributions
    assert ranked[0].score > 0.0


def test_constructor_none_handling():
    """Test that constructor properly handles None values"""
    # All None values should use defaults from SSOT or hardcoded defaults
    r = UniverseRanker(wL=None, wS=None, wP=None, wR=None, 
                      add_thresh=None, drop_thresh=None, min_dwell=None)
    
    # Should not raise exceptions and should have valid default values
    assert hasattr(r, 'wL')
    assert hasattr(r, 'wS') 
    assert hasattr(r, 'wP')
    assert hasattr(r, 'wR')
    assert hasattr(r, 'addT')
    assert hasattr(r, 'dropT')
    assert hasattr(r, 'min_dwell')
    
    # Weights should sum to 1.0 (normalized)
    assert abs(r.wL + r.wS + r.wP + r.wR - 1.0) < 1e-6


if __name__ == "__main__":
    test_none_inputs_are_coerced()
    test_mixed_none_and_values()
    test_constructor_none_handling()
    print("All tests passed!")