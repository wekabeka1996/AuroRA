"""
Unit Tests for Reward Manager Trail Logic
========================================

Tests trail reward tracking, negative reward protection, and decision attribution.
"""

import json
from pathlib import Path
import tempfile
import time

import pytest

from core.governance.reward_manager import RewardManager, create_enhanced_decision


class TestRewardManagerTrail:
    """Test reward manager trail functionality."""

    @pytest.fixture
    def reward_manager(self):
        """Create reward manager with test config."""
        config = {
            "negative_reward_threshold": -0.5,
            "trail_decay_factor": 0.95,
            "max_trail_age_sec": 3600
        }
        return RewardManager(config)

    def test_create_decision_with_trail(self, reward_manager):
        """Test decision creation with trail tracking."""
        scores = {"p_fill": 0.8, "spread_bps": 1.5}

        decision = reward_manager.create_decision_with_trail(
            route="maker",
            why_code="OK_ROUTE_MAKER",
            scores=scores,
            initial_reward=0.5
        )

        assert decision.route == "maker"
        assert decision.why_code == "OK_ROUTE_MAKER"
        assert decision.scores == scores
        assert decision.trail_reward == 0.5

        # Check trail was created
        active_trails = reward_manager.get_active_trails()
        assert len(active_trails) == 1
        assert active_trails[0]["route"] == "maker"
        assert active_trails[0]["current_reward"] == 0.5

    def test_negative_reward_protection(self, reward_manager):
        """Test protection against excessive negative rewards."""
        scores = {"edge_after_latency_bps": -2.0}

        # Create decision with large negative reward
        decision = reward_manager.create_decision_with_trail(
            route="deny",
            why_code="WHY_UNATTRACTIVE",
            scores=scores,
            initial_reward=-1.5  # Below threshold
        )

        # Should be clamped to threshold
        assert decision.trail_reward == -0.5

        # Check trail records original value
        trails = reward_manager.get_active_trails()
        assert len(trails) == 1
        assert trails[0]["initial_reward"] == -1.5
        assert trails[0]["current_reward"] == -0.5

    def test_trail_reward_updates(self, reward_manager):
        """Test updating trail rewards over time."""
        decision = reward_manager.create_decision_with_trail(
            route="taker",
            why_code="OK_ROUTE_TAKER",
            scores={"p_fill": 0.3},
            initial_reward=0.2
        )

        # Get decision ID from active trails
        trails = reward_manager.get_active_trails()
        decision_id = trails[0]["decision_id"]

        # Update reward
        success = reward_manager.update_trail_reward(
            decision_id,
            new_reward=0.8,
            metadata={"reason": "improved_fill"}
        )

        assert success

        # Check updated reward with decay
        trail_summary = reward_manager.get_trail_summary(decision_id)
        expected_reward = 0.8 * 0.95  # decay factor applied
        assert trail_summary["current_reward"] == expected_reward
        assert trail_summary["total_updates"] == 1

    def test_trail_closure(self, reward_manager):
        """Test closing decision trails."""
        decision = reward_manager.create_decision_with_trail(
            route="maker",
            why_code="OK_ROUTE_MAKER",
            scores={"spread_bps": 2.0},
            initial_reward=0.3
        )

        trails = reward_manager.get_active_trails()
        decision_id = trails[0]["decision_id"]

        # Close trail
        closed_trail = reward_manager.close_trail(decision_id, final_reward=0.9)

        assert closed_trail is not None
        assert not closed_trail.is_active
        assert closed_trail.current_reward == 0.9

        # Should no longer be in active trails
        active_trails = reward_manager.get_active_trails()
        assert len(active_trails) == 0

    def test_performance_metrics(self, reward_manager):
        """Test performance metrics calculation."""
        # Create multiple decisions
        decisions = [
            ("maker", "OK_ROUTE_MAKER", 0.5),
            ("taker", "OK_ROUTE_TAKER", 0.3),
            ("deny", "WHY_UNATTRACTIVE", -0.2),
            ("maker", "OK_ROUTE_MAKER", 0.7)
        ]

        for i, (route, why_code, reward) in enumerate(decisions):
            decision = reward_manager.create_decision_with_trail(
                route=route,
                why_code=why_code,
                scores={"test": 1.0, "decision_num": i},  # Make each unique
                initial_reward=reward
            )
            # Small delay to ensure unique timestamps
            time.sleep(0.001)

        metrics = reward_manager.get_performance_metrics()

        assert metrics["total_decisions"] == 4
        assert metrics["active_trails"] == 4
        assert "avg_reward" in metrics
        assert metrics["route_distribution"]["maker"] == 2
        assert metrics["route_distribution"]["taker"] == 1
        assert metrics["route_distribution"]["deny"] == 1

    def test_trail_cleanup(self, reward_manager):
        """Test cleanup of old trails."""
        # Create reward manager with very short max age
        short_config = {
            "negative_reward_threshold": -0.5,
            "trail_decay_factor": 0.95,
            "max_trail_age_sec": 1  # 1 second
        }
        rm = RewardManager(short_config)

        # Create decision
        decision = rm.create_decision_with_trail(
            route="maker",
            why_code="OK_ROUTE_MAKER",
            scores={"test": 1.0},
            initial_reward=0.5
        )

        assert len(rm.get_active_trails()) == 1

        # Wait for cleanup
        time.sleep(1.1)

        # Create another decision to trigger cleanup
        rm.create_decision_with_trail(
            route="taker",
            why_code="OK_ROUTE_TAKER",
            scores={"test": 1.0},
            initial_reward=0.3
        )

        # Old trail should be cleaned up
        active_trails = rm.get_active_trails()
        assert len(active_trails) == 1
        assert active_trails[0]["route"] == "taker"

    def test_export_trails_json(self, reward_manager):
        """Test JSON export functionality."""
        # Create some trails
        reward_manager.create_decision_with_trail(
            route="maker",
            why_code="OK_ROUTE_MAKER",
            scores={"p_fill": 0.8},
            initial_reward=0.6
        )

        # Export to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            temp_path = f.name

        try:
            reward_manager.export_trails_json(temp_path)

            # Verify export
            with open(temp_path) as f:
                exported_data = json.load(f)

            assert "timestamp" in exported_data
            assert "config" in exported_data
            assert "trails" in exported_data
            assert len(exported_data["trails"]) == 1

            trail_data = list(exported_data["trails"].values())[0]
            assert trail_data["route"] == "maker"
            assert trail_data["initial_reward"] == 0.6

        finally:
            Path(temp_path).unlink(missing_ok=True)


class TestBackwardCompatibility:
    """Test backward compatibility functions."""

    def test_create_enhanced_decision_with_manager(self):
        """Test factory function with reward manager."""
        rm = RewardManager()

        decision = create_enhanced_decision(
            route="taker",
            why_code="OK_ROUTE_TAKER",
            scores={"spread_bps": 3.0},
            reward_manager=rm,
            initial_reward=0.4
        )

        assert decision.route == "taker"
        assert decision.trail_reward == 0.4
        assert len(rm.get_active_trails()) == 1

    def test_create_enhanced_decision_without_manager(self):
        """Test factory function without reward manager."""
        decision = create_enhanced_decision(
            route="deny",
            why_code="WHY_SLA_LATENCY",
            scores={"latency_ms": 300},
            initial_reward=-0.1
        )

        assert decision.route == "deny"
        assert decision.trail_reward == -0.1
        # No trail tracking without manager


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
