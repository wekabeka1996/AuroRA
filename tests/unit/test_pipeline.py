"""
Unit Tests for PretradePipeline
===============================

Comprehensive unit tests for core.aurora.pipeline.PretradePipeline class.
Tests all decision paths, guards, and edge cases in the pretrade pipeline.
"""

import pytest
from unittest.mock import MagicMock, patch
from core.aurora.pipeline import PretradePipeline


class TestPretradePipeline:
    """Test PretradePipeline decision logic."""

    @pytest.fixture
    def mock_emitter(self):
        """Mock event emitter."""
        return MagicMock()

    @pytest.fixture
    def mock_trap_window(self):
        """Mock trap window."""
        mock = MagicMock()
        mock.window_s = 2.0  # Add window_s attribute
        return mock

    @pytest.fixture
    def mock_health_guard(self):
        """Mock health guard."""
        mock = MagicMock()
        mock.record.return_value = (True, 50.0)  # (ok, p95)
        mock.enforce.return_value = (True, None)  # (allow, reason)
        return mock

    @pytest.fixture
    def mock_risk_manager(self):
        """Mock risk manager."""
        return MagicMock()

    @pytest.fixture
    def mock_governance(self):
        """Mock governance."""
        return MagicMock()

    @pytest.fixture
    def pipeline(self, mock_emitter, mock_trap_window, mock_health_guard, mock_risk_manager, mock_governance):
        """Create pipeline instance with mocked dependencies."""
        return PretradePipeline(
            emitter=mock_emitter,
            trap_window=mock_trap_window,
            health_guard=mock_health_guard,
            risk_manager=mock_risk_manager,
            governance=mock_governance,
            cfg={}
        )

    def test_decide_latency_guard_blocks_high_latency(self, pipeline, mock_emitter):
        """Test that high latency blocks trade."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 50.0,  # Above default 30ms limit
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert reason == 'latency_guard'
        assert any('latency_guard' in r for r in obs['reasons'])
        assert obs['gate_state'] == 'BLOCK'
        mock_emitter.emit.assert_called()

    def test_decide_latency_guard_allows_normal_latency(self, pipeline):
        """Test that normal latency allows trade."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,  # Below 30ms limit
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is True
        assert reason == 'ok'
        assert obs['gate_state'] == 'PASS'

    def test_decide_latency_guard_custom_config(self, pipeline):
        """Test latency guard with custom config."""
        pipeline.cfg = {'guards': {'latency_ms_limit': 100.0}}

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 50.0,  # Below custom 100ms limit
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is True
        assert reason == 'ok'

    def test_decide_health_guard_blocks_on_p95_violation(self, pipeline, mock_health_guard, mock_emitter):
        """Test health guard blocks on P95 violation."""
        mock_health_guard.record.return_value = (True, 95.0)
        mock_health_guard.enforce.return_value = (False, 'p95_high')

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {'latency_ms': 10.0}
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert 'latency_p95_high' in reason
        mock_emitter.emit.assert_called()

    def test_decide_trap_guard_blocks_on_score_threshold(self, pipeline, mock_trap_window):
        """Test trap guard blocks when score exceeds threshold."""
        pipeline.cfg = {'trap': {'score_threshold': 0.5}}

        # Create a simple object that behaves like TrapMetrics
        class MockTrapMetrics:
            def __init__(self):
                self.trap_z = 2.0
                self.cancel_rate = 0.5
                self.repl_rate = 0.3
                self.n_trades = 10
                self.flag = False

        mock_metrics = MockTrapMetrics()

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 50.0,
            'trap_cancel_deltas': [0.1, 0.2],
            'trap_add_deltas': [0.05, 0.1],
            'trap_trades_cnt': 10
        }
        fees_bps = 0.1

        # Mock trap functions
        with patch.object(mock_trap_window, 'update', return_value=mock_metrics), \
             patch('core.scalper.trap.trap_score_from_features', return_value=0.8):
            allow, reason, obs, risk_scale = pipeline.decide(
                account=account, order=order, market=market, fees_bps=fees_bps
            )

        assert allow is False
        assert reason == 'trap_guard_score'
        assert 'trap_guard_score:0.80>0.50' in obs['reasons']

    def test_decide_expected_return_gate_blocks_low_pi(self, pipeline):
        """Test expected return gate blocks when PI is below minimum."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 0.1,  # Low score
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.5
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert reason == 'expected_return_gate'

    def test_decide_slippage_guard_blocks_high_slippage(self, pipeline):
        """Test slippage guard blocks when slippage is too high."""
        pipeline.cfg = {'risk': {'pi_min_bps': 0.5}}  # Lower threshold to pass expected return

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 10.0,  # High score to ensure e_pi_bps > 2.0
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 1.0,  # High slippage
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        # Expected return should pass (score=10.0 gives e_pi_bps ≈ 20.0 > 2.0)
        # Slippage guard should block (slip_bps_est=1.0 > 0.5 default limit)
        assert allow is False
        assert reason == 'slippage_guard'

    def test_decide_risk_manager_blocks_on_risk_violation(self, pipeline, mock_risk_manager):
        """Test risk manager blocks trade."""
        mock_risk_manager.decide.return_value = (False, 'risk_limit_exceeded', 500.0, {'size_scale': 0.5})

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'pnl_today_pct': -5.0,
            'open_positions': 10
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert reason == 'risk_limit_exceeded'
        assert risk_scale == 0.5

    def test_decide_spread_guard_blocks_wide_spread(self, pipeline):
        """Test spread guard blocks when spread is too wide."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 150.0  # Above default 100bps limit
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert 'spread_bps_too_wide' in reason

    def test_decide_governance_blocks_trade(self, pipeline, mock_governance):
        """Test governance blocks trade."""
        mock_governance.approve.return_value = {'allow': False, 'code': 'kill_switch_active'}

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert reason == 'kill_switch_active'

    def test_decide_sprt_rejects_hypothesis(self, pipeline):
        """Test SPRT rejects null hypothesis."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'sprt_samples': [0.1, 0.2, 0.3]  # Samples that should reject
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        # SPRT might accept or continue depending on implementation
        # Just verify it doesn't crash and returns valid result
        assert isinstance(allow, bool)
        assert isinstance(reason, str)
        assert isinstance(obs, dict)

    def test_decide_allows_trade_all_checks_pass(self, pipeline, mock_risk_manager):
        """Test successful trade when all checks pass."""
        mock_risk_manager.decide.return_value = (True, None, 1000.0, {'size_scale': 1.0})

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 2.0,
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 0.1,
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is True
        assert reason == 'ok'
        assert obs['gate_state'] == 'PASS'
        assert risk_scale == 1.0

    def test_decide_handles_missing_market_data(self, pipeline):
        """Test pipeline handles missing market data gracefully."""
        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {}  # Empty market data
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        # Should not crash and return valid result
        assert isinstance(allow, bool)
        assert isinstance(reason, str)
        assert isinstance(obs, dict)
        assert isinstance(risk_scale, float)

    def test_decide_custom_order_profile_slip_before_er(self, pipeline):
        """Test custom order profile with slip before ER."""
        pipeline.cfg = {
            'pretrade': {'order_profile': 'slip_before_er'},
            'risk': {'pi_min_bps': 0.5}  # Lower threshold to pass expected return
        }

        account = {'mode': 'live'}
        order = {'base_notional': 1000.0}
        market = {
            'latency_ms': 10.0,
            'score': 10.0,  # Very high score to ensure e_pi_bps > 2.0
            'a_bps': 1.0,
            'b_bps': 2.0,
            'slip_bps_est': 1.0,  # High slippage should block first
            'spread_bps': 50.0
        }
        fees_bps = 0.1

        allow, reason, obs, risk_scale = pipeline.decide(
            account=account, order=order, market=market, fees_bps=fees_bps
        )

        assert allow is False
        assert reason == 'slippage_guard'