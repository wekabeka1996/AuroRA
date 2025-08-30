"""
Tests — Risk Guards Live Integration
====================================

Test risk guards integration in live trading pipeline.
"""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from core.risk.guards import RiskGuards, RiskLimits, RiskCheckResult


class TestRiskGuardsLive:
    """Test risk guards in live trading context."""
    
    @pytest.fixture
    def risk_guards(self):
        """Create risk guards with test configuration."""
        limits = RiskLimits(
            dd_day_bps=300.0,
            position_usd=25000.0,
            order_min_usd=10.0,
            order_max_usd=5000.0,
            cvar_usd=150.0,
            evt_quantile=0.999,
            evt_max_loss_usd=400.0
        )
        return RiskGuards(limits=limits)
    
    def test_dd_cap_breach(self, risk_guards):
        """Test daily DD cap breach denies trade."""
        # Setup: equity down 400bps (breach of 300bps limit)
        risk_guards.reset_daily_start(10000.0)  # Set initial equity
        risk_guards.update_equity(6000.0)  # Down from 10000 to 6000
        
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 6000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_DD"
        assert "dd_bps" in result.details
        assert result.details["dd_bps"] > 300.0
    
    def test_inventory_cap_breach(self, risk_guards):
        """Test inventory cap breach denies trade."""
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {
            "equity_usd": 10000.0, 
            "positions": {"BTCUSDT": 0.6}  # 0.6 * 50000 = 30000 USD (breach of 25000 limit)
        }
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_INV"
        assert "net_position_usd" in result.details
        assert result.details["net_position_usd"] > 25000.0
    
    def test_min_notional_breach(self, risk_guards):
        """Test minimum notional breach denies trade."""
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.0001, "price": 50000.0}  # 5 USD notional
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_MIN_NOTIONAL"
        assert result.details["order_notional"] < 10.0
    
    def test_max_notional_breach(self, risk_guards):
        """Test maximum notional breach denies trade."""
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.2, "price": 50000.0}  # 10000 USD notional
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_MAX_NOTIONAL"
        assert result.details["order_notional"] > 5000.0
    
    def test_cvar_breach_with_mock_model(self, risk_guards):
        """Test CVaR breach denies trade when model predicts high risk."""
        # Mock CVaR model that returns breach value
        mock_cvar_model = MagicMock()
        mock_cvar_model.predict_cvar.return_value = -200.0  # Breach of -150 limit
        risk_guards.cvar_model = mock_cvar_model
        
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_CVAR"
        assert "cvar_usd" in result.details
        assert result.details["cvar_usd"] < -150.0
    
    def test_evt_breach_with_mock_model(self, risk_guards):
        """Test EVT breach denies trade when model predicts extreme loss."""
        # Mock EVT model that returns breach value
        mock_evt_model = MagicMock()
        mock_evt_model.predict_quantile.return_value = 500.0  # Breach of 400 limit
        risk_guards.evt_model = mock_evt_model
        
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == False
        assert result.why_code == "WHY_RISK_GUARD_EVT"
        assert "evt_loss_usd" in result.details
        assert result.details["evt_loss_usd"] > 400.0
    
    def test_positive_case_all_checks_pass(self, risk_guards):
        """Test that valid trade passes all risk checks."""
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.01, "price": 50000.0}  # 500 USD notional
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        assert result.allow == True
        assert result.why_code == "OK_RISK_GUARD"
        assert "checks_passed" in result.details
        assert len(result.details["checks_passed"]) == 5  # dd, inventory, notional, cvar, evt
    
    def test_model_failures_are_safe(self, risk_guards):
        """Test that CVaR/EVT model failures don't block trades (fail-safe)."""
        # Mock models that raise exceptions
        mock_cvar_model = MagicMock()
        mock_cvar_model.predict_cvar.side_effect = Exception("Model error")
        risk_guards.cvar_model = mock_cvar_model
        
        mock_evt_model = MagicMock()
        mock_evt_model.predict_quantile.side_effect = Exception("Model error")
        risk_guards.evt_model = mock_evt_model
        
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.01, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 10000.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        # Should still allow despite model failures (fail-safe)
        assert result.allow == True
        assert result.why_code == "OK_RISK_GUARD"
    
    def test_equity_tracking(self, risk_guards):
        """Test equity tracking for DD calculations."""
        # Initial equity
        risk_guards.reset_daily_start(10000.0)
        
        # Update to lower equity (50bps DD)
        risk_guards.update_equity(9950.0)
        
        intent = {"symbol": "BTCUSDT", "side": "buy", "qty": 0.001, "price": 50000.0}
        snapshot = {"mid_price": 50000.0, "spread_bps": 2.0, "latency_ms": 10.0}
        account_state = {"equity_usd": 9950.0, "positions": {}}
        
        result = risk_guards.pre_trade_check(intent, snapshot, account_state)
        
        # Should allow (50bps DD < 300bps limit)
        assert result.allow == True
        assert result.why_code == "OK_RISK_GUARD"
        # DD check passed, so dd_bps not included in details
        assert "dd_bps" not in result.details


if __name__ == "__main__":
    pytest.main([__file__, "-v"])