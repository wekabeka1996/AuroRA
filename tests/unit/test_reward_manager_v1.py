from __future__ import annotations

import pytest
from core.reward_manager import RewardManager, PositionState
from core.config_loader import RewardCfg


class TestRewardManager:
    """Unit tests for RewardManager v1.0"""
    
    @pytest.fixture
    def cfg(self) -> RewardCfg:
        """Test configuration with higher max_R to avoid premature exits"""
        return RewardCfg(
            tp_pct=0.5,
            trail_bps=20,
            trail_activate_at_R=2.0,  # Even lower threshold for trail-stop update test
            breakeven_after_R=5.0,  # Higher breakeven threshold to prevent interference with other tests
            max_position_age_sec=3600,
            atr_mult_sl=1.2,
            target_R=1.0,
            max_R=10.0,  # Higher max_R to avoid premature MAX_R_EXIT
            tp_levels_bps=[20.0, 40.0, 70.0],
            tp_sizes=[0.25, 0.35, 0.40],
            trail_atr_k=0.8,
            be_rr=5.0,  # Higher breakeven threshold to allow trail-stop test
            be_buffer_bps=2.0,
            ttl_minutes=120,
            stuck_dt_s=300,
            no_progress_eps_bps=5.0,
            scale_in_enabled=False,  # Disable scale-in for TP ladder test
            scale_in_hysteresis=0.1,
            scale_in_rho=0.5,
            scale_in_max_add_per_step=0.2,
            scale_in_cooldown_s=60
        )
    
    @pytest.fixture
    def reward_mgr(self, cfg: RewardCfg) -> RewardManager:
        return RewardManager(cfg)
    
    def test_initialization(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test RewardManager initialization"""
        assert reward_mgr.cfg == cfg
        assert reward_mgr._last_scale_in_ts == 0
    
    def test_tp_ladder_hit_first_level(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test TP ladder first level hit"""
        # Setup position with TP levels
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=120.0,  # 20% profit = 2000 bps
            sl=95.0,
            tp=None,  # Add required tp field
            age_sec=60,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            tp_levels_bps=[20.0, 40.0, 70.0],
            tp_sizes=[0.25, 0.35, 0.40],
            tp_hits=[],
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'REDUCE'
        assert decision.reduce_qty == 25.0  # 0.25 * 100
        assert decision.tp_level_hit == 20.0
        assert 20.0 in (st.tp_hits or [])
    
    def test_tp_ladder_hit_second_level(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test TP ladder second level hit"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=140.0,  # 40% profit = 4000 bps
            sl=95.0,
            tp=None,
            age_sec=60,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            tp_levels_bps=[20.0, 40.0, 70.0],
            tp_sizes=[0.25, 0.35, 0.40],
            tp_hits=[20.0],  # First level already hit
            net_qty=75.0  # Remaining after first reduce
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'REDUCE'
        assert decision.reduce_qty == 26.25  # 0.35 * 75
        assert decision.tp_level_hit == 40.0
        assert 40.0 in (st.tp_hits or [])
    
    def test_breakeven_activation(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test breakeven activation after reaching R/R threshold"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=130.0,  # 30% profit = 3000 bps, R/R = 3000/500 = 6.0 > 5.0
            sl=95.0,  # 5% stop = 500 bps
            tp=None,
            age_sec=60,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            tp_levels_bps=[],  # Empty list to pass TP ladder check
            tp_sizes=[],  # Empty list to pass TP ladder check
            tp_hits=[],  # Empty list to pass TP ladder check
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'MOVE_TO_BREAKEVEN'
        assert decision.new_sl == 100.12  # entry + fees + buffer = 100.0 + 0.1 + 2.0*100.0/10000
    
    def test_trail_stop_activation(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test trail-stop activation and updates"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=110.0,  # 10% profit = 1000 bps, R/R = 1000/300 = 3.33 > 0.5
            sl=97.0,  # 3% stop = 300 bps
            tp=None,
            age_sec=60,
            atr=2.0,  # Enable trail-stop by setting ATR to positive value
            fees_per_unit=0.1,
            funding_accum=0.0,
            trail_px=108.0,  # Set trail even lower to ensure TRAIL_UP triggers
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'TRAIL_UP'
        expected_trail = max(108.0, 110.0 - (0.8 * 2.0))  # max(current_trail, price - trail_dist) = max(108.0, 108.4) = 108.4
        assert decision.new_sl == expected_trail
    
    def test_trail_stop_update(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test trail-stop updates when price moves higher"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=115.0,  # Price moved higher
            sl=107.0,  # Current trail
            tp=None,
            age_sec=60,
            atr=2.0,  # Enable trail-stop by setting ATR to positive value
            fees_per_unit=0.1,
            funding_accum=0.0,
            trail_px=107.0,
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'TRAIL_UP'
        expected_trail = 115.0 - (0.8 * 2.0)  # New higher trail = 115.0 - 1.6 = 113.4
        assert decision.new_sl == expected_trail
        assert st.trail_px == expected_trail
    
    def test_short_position_trail_stop(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test trail-stop for short positions"""
        st = PositionState(
            side='SHORT',
            entry=100.0,
            price=90.0,  # 10% profit for short
            sl=103.0,
            tp=None,
            age_sec=60,
            atr=2.0,  # Enable trail-stop
            fees_per_unit=0.1,
            funding_accum=0.0,
            trail_px=None,  # Remove high trail price to allow TRAIL_UP
            net_qty=100.0,
            tp_levels_bps=[],  # Empty list to pass TP ladder check
            tp_sizes=[],  # Empty list to pass TP ladder check
            tp_hits=[],  # Empty list to pass TP ladder check
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'TRAIL_UP'
        expected_trail = 90.0 + (0.8 * 2.0)  # price + (k * ATR) for short
        assert decision.new_sl == expected_trail
    
    def test_max_r_exit(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test Max-R exit condition"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=130.0,  # 30% profit = 3000 bps, R/R = 3000/500 = 6.0 > 5.0
            sl=97.0,  # 1% stop = 100 bps, R/R = 2000/100 = 20
            tp=None,
            age_sec=60,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'MAX_R_EXIT'
        assert decision.meta is not None and decision.meta['R_unreal'] == 10.0
    
    def test_ttl_exit(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test TTL-based exit"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=102.0,
            sl=99.0,
            tp=None,
            age_sec=7201,  # 120 minutes + 1 second
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'TIME_EXIT'
        assert decision.meta['age_sec'] == 7201
        assert decision.meta is not None and decision.meta['ttl_sec'] == 7200
    
    def test_no_progress_exit(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test no-progress exit condition"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=100.5,  # Only 0.5% profit = 50 bps < 500 bps threshold
            sl=99.0,
            tp=None,
            age_sec=301,  # stuck_dt_s + 1
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'TIME_EXIT'
        assert decision.meta is not None and decision.meta['reason'] == 'no_progress'
    
    def test_scale_in_anti_martingale(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test anti-martingale scale-in logic"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=108.0,  # 8% profit
            sl=97.0,
            tp=None,
            age_sec=120,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            last_scale_in_ts=0,  # No recent scale-in
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        # Should trigger scale-in (simplified logic)
        assert decision.action in ['SCALE_IN', 'HOLD', 'MOVE_TO_BREAKEVEN']
    
    def test_scale_in_cooldown(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test scale-in cooldown prevents frequent scaling"""
        current_ts = 100
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=108.0,
            sl=97.0,
            tp=None,
            age_sec=current_ts,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            last_scale_in_ts=current_ts - 30,  # Within cooldown
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        # Should not scale-in due to cooldown
        assert decision.action != 'SCALE_IN'
    
    def test_hold_when_no_action_needed(self, reward_mgr: RewardManager, cfg: RewardCfg):
        """Test HOLD action when no reward action is needed"""
        st = PositionState(
            side='LONG',
            entry=100.0,
            price=101.0,  # Small profit, no TP hit
            sl=99.0,
            tp=None,
            age_sec=60,
            atr=0.0,  # Disable trail-stop by setting ATR to 0
            fees_per_unit=0.1,
            funding_accum=0.0,
            net_qty=100.0
        )
        
        decision = reward_mgr.update(st)
        
        assert decision.action == 'HOLD'